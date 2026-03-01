import os
import time
import threading
import yt_dlp
import requests
import uuid
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
# Simplified CORS for debugging - allows all origins and headers temporarily
CORS(app)

# SECURITY CONFIG
ALLOWED_ORIGINS = [
    "https://argha-7.blogspot.com",  # Replace with your actual blogger URL
    "http://localhost:5000",          # For local testing
    "http://127.0.0.1:5000"
]
APP_SECRET = "insta_pro_ai_secure_99" # Simple secret key

def verify_request():
    """Verify that the request comes from our site and has the secret."""
    secret = request.headers.get('X-App-Secret')
    print(f"DEBUG: Headers received: {dict(request.headers)}")
    print(f"DEBUG: Secret received: {secret}")
    
    if secret != APP_SECRET:
        print("DEBUG: Secret mismatch!")
        return False
    return True

# Rate Limiter setup (Prevents abuse)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

# Configuration
DOWNLOAD_FOLDER = os.path.join(os.getcwd(), 'downloads')
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Usage tracking (Credits & Cash System)
# Format: {ip: {'credits': 50, 'balance': 0.0, 'referral_id': '...', 'last_activity': timestamp}}
user_credits = {}
DEFAULT_CREDITS = 50
DOWNLOAD_COST = 10
SHARE_REWARD = 20
DOWNLOAD_CASH_REWARD = 0.50 # ₹0.50 per download
REFERRAL_CASH_REWARD = 2.00  # ₹2.00 per new referral

def generate_ref_id():
    return str(uuid.uuid4())[:8]

def get_user_data(ip):
    """Helper to get or initialize user data with referral tracking."""
    if ip not in user_credits:
        # Check if the request contains a referral ID
        ref_id = request.json.get('ref') if request.is_json else request.args.get('ref')
        
        user_credits[ip] = {
            'credits': DEFAULT_CREDITS, 
            'balance': 0.0,
            'referral_id': generate_ref_id(),
            'last_activity': time.time()
        }
        
        # Reward the referrer if valid
        if ref_id:
            for other_ip, data in user_credits.items():
                if data['referral_id'] == ref_id and other_ip != ip:
                    data['balance'] += REFERRAL_CASH_REWARD
                    print(f"REFERRAL REWARD: {other_ip} earned ₹{REFERRAL_CASH_REWARD} for referring {ip}")
                    break
                    
    return user_credits[ip]
job_status = {}

# Cleanup task to delete files older than 20 minutes
def cleanup_files():
    while True:
        now = time.time()
        for f in os.listdir(DOWNLOAD_FOLDER):
            file_path = os.path.join(DOWNLOAD_FOLDER, f)
            if os.stat(file_path).st_mtime < now - 1200: # 20 minutes
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    print(f"Deleted old file: {f}")
        time.sleep(300)

threading.Thread(target=cleanup_files, daemon=True).start()

def trigger_github_action(video_url, job_id):
    """Triggers the GitHub Action workflow as a backup."""
    token = os.environ.get('GH_TOKEN')
    repo = os.environ.get('GH_REPO') # e.g., "Argha-7/insta-downloader-web"
    
    if not token or not repo:
        print("GITHUB ERROR: GH_TOKEN or GH_REPO not set in Secrets.")
        return False

    url = f"https://api.github.com/repos/{repo}/actions/workflows/download.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    # Current Space URL for callback
    space_name = os.environ.get('SPACE_ID', '')
    if space_name:
        callback_url = f"https://{space_name.replace('/', '-')}.hf.space/github-callback?job_id={job_id}"
    else:
        # Fallback for local testing (won't work for callback but for trigger)
        callback_url = ""

    payload = {
        "ref": "main",
        "inputs": {
            "video_url": video_url,
            "callback_url": callback_url
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 204:
            print(f"GitHub Action triggered for Job: {job_id}")
            return True
        else:
            print(f"GitHub API Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"GitHub Trigger Exception: {e}")
        return False

def download_video(url):
    """Main download logic with local-first, then GitHub failover."""
    if '?' in url:
        url = url.split('?')[0]
    
    # 1. Try Local Download (Fastest)
    ydl_opts = {
        'format': 'b[ext=mp4]/b', 
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'insta_{int(time.time())}_%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'nocheckcertificate': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename):
                return "SUCCESS", {
                    'filename': os.path.basename(filename),
                    'title': info.get('title', 'Instagram Video'),
                    'thumbnail': info.get('thumbnail', '')
                }
    except Exception as e:
        err_str = str(e)
        print(f"LOCAL DOWNLOAD FAILED: {err_str}")
        
        # 2. Trigger GitHub Actions if blocked or extraction fails
        if "403" in err_str or "Forbidden" in err_str or "address associated" in err_str or "ExtractorError" in err_str or "JSON" in err_str:
            job_id = str(uuid.uuid4())
            job_status[job_id] = {'status': 'pending', 'filename': None, 'timestamp': time.time()}
            if trigger_github_action(url, job_id):
                return "PENDING_GITHUB", job_id
        
        return "FAILED", f"Error: {err_str[:100]}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
@limiter.limit("5 per minute")
def handle_download():
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    ip = get_remote_address()
    user_data = get_user_data(ip)
    
    if user_data['credits'] < DOWNLOAD_COST:
        return jsonify({'success': False, 'message': f'Insufficient credits ({user_data["credits"]}). Share on WhatsApp to earn more!'}), 403

    data = request.json
    url = data.get('url')
    if not url: return jsonify({'success': False, 'message': 'No URL provided'}), 400
    
    status, result = download_video(url)
    
    if status == "SUCCESS":
        user_data['credits'] -= DOWNLOAD_COST
        user_data['balance'] += DOWNLOAD_CASH_REWARD
        raw_thumb = result.get('thumbnail', '')
        proxy_thumb = f"{request.host_url}proxy-img?url={raw_thumb}" if raw_thumb else ""
        
        return jsonify({
            'success': True, 
            'status': 'ready', 
            'filename': result['filename'],
            'title': result['title'],
            'thumbnail': proxy_thumb,
            'credits': user_data['credits'],
            'balance': round(user_data['balance'], 2)
        })
    elif status == "PENDING_GITHUB":
        user_data['credits'] -= DOWNLOAD_COST
        user_data['balance'] += DOWNLOAD_CASH_REWARD
        # GitHub action update: we won't have metadata immediately
        return jsonify({
            'success': True, 
            'status': 'pending', 
            'job_id': result, 
            'credits': user_data['credits'], 
            'balance': round(user_data['balance'], 2),
            'message': 'Hugging Face is blocked. Switching to GitHub Backup...' 
        })
    else:
        return jsonify({'success': False, 'message': result})

@app.route('/check-limit', methods=['POST'])
def check_limit():
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    ip = get_remote_address()
    user_data = get_user_data(ip)
    return jsonify({
        'credits': user_data['credits'],
        'balance': round(user_data['balance'], 2),
        'referral_id': user_data['referral_id'],
        'cost': DOWNLOAD_COST,
        'reward': SHARE_REWARD
    })

@app.route('/withdraw', methods=['POST'])
def handle_withdraw():
    """Placeholder for withdrawal requests."""
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    ip = get_remote_address()
    user_data = get_user_data(ip)
    upi_id = request.json.get('upi_id')
    
    if user_data['balance'] < 50:
        return jsonify({'success': False, 'message': 'Minimum withdrawal is ₹50.00'}), 400
        
    # In a real app, you'd save this to a database
    print(f"WITHDRAW REQUEST: User {ip} requested withdrawal of ₹{user_data['balance']} to UPI: {upi_id}")
    return jsonify({'success': True, 'message': 'Withdrawal request sent! We will process it within 24 hours.'})

@app.route('/reward-share', methods=['POST'])
def reward_share():
    """Reward user for sharing the site."""
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    ip = get_remote_address()
    user_data = get_user_data(ip)
    user_data['credits'] += SHARE_REWARD
    return jsonify({
        'success': True,
        'message': f'Gift Received! +{SHARE_REWARD} credits added.',
        'credits': user_data['credits']
    })

@app.route('/proxy-img')
def proxy_image():
    """Proxies images to bypass CORS."""
    url = request.args.get('url')
    if not url: return "No URL", 400
    try:
        resp = requests.get(url, stream=True, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        })
        return (resp.content, resp.status_code, resp.headers.items())
    except Exception as e:
        return str(e), 500

@app.route('/preview', methods=['POST'])
def get_preview():
    """Fetches metadata (title/thumbnail) without downloading."""
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    url = request.json.get('url')
    if not url: return jsonify({'success': False, 'message': 'No URL provided'}), 400
    
    if '?' in url: url = url.split('?')[0]
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            raw_thumb = info.get('thumbnail', '')
            # Use our proxy for the thumbnail
            proxy_thumb = f"{request.host_url}proxy-img?url={raw_thumb}" if raw_thumb else ""
            
            return jsonify({
                'success': True,
                'title': info.get('title', 'Instagram Video'),
                'thumbnail': proxy_thumb
            })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 403

@app.route('/status/<job_id>')
def check_status(job_id):
    """Blogger polls this to see if GitHub is done."""
    status = job_status.get(job_id)
    if not status:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(status)

@app.route('/github-callback', methods=['POST'])
def github_callback():
    """GitHub Action POSTs the file here."""
    job_id = request.args.get('job_id')
    if not job_id or job_id not in job_status:
        return "Invalid Job ID", 400
    
    if 'file' not in request.files:
        return "No file", 400
    
    file = request.files['file']
    filename = f"gh_{int(time.time())}_{file.filename}"
    file.save(os.path.join(DOWNLOAD_FOLDER, filename))
    
    job_status[job_id] = {'status': 'ready', 'filename': filename}
    print(f"Job {job_id} READY via GitHub Callback.")
    return "OK", 200

@app.route('/files/<path:filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    # Local fallback for GH_REPO
    if not os.environ.get('GH_REPO'):
        os.environ['GH_REPO'] = "Argha-7/insta-downloader-web"
    app.run(host='0.0.0.0', port=7860)
