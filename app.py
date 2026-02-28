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
import firebase_admin
from firebase_admin import credentials, auth, firestore

# Firebase Initialization
# You must provide 'serviceAccountKey.json' in the same directory
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate('serviceAccountKey.json')
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    FIREBASE_ENABLED = True
    print("FIREBASE: Successfully initialized.")
except Exception as e:
    FIREBASE_ENABLED = False
    print(f"FIREBASE WARNING: Service account not found or invalid: {e}")

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

# Usage tracking (Universal System)
# Format for Guest: {ip: {'count': 0, 'balance': 0.0, 'last_reset': timestamp}}
user_usage = {}
DAILY_LIMIT = 10
REWARD_PER_DOWNLOAD = 0.20

def get_user_data(token_id=None, ip=None):
    """Get user stats from Firestore (if token) or memory (if guest)."""
    now = time.time()
    
    # CASE 1: Authenticated User (Firebase)
    if token_id and FIREBASE_ENABLED:
        try:
            decoded_token = auth.verify_id_token(token_id)
            uid = decoded_token['uid']
            user_ref = db.collection('users').document(uid)
            doc = user_ref.get()
            
            if doc.exists:
                data = doc.to_dict()
                # Check for daily reset (00:00 server time or 24h)
                if now - data.get('last_reset', 0) > 86400:
                    data['count'] = 0
                    data['last_reset'] = now
                    user_ref.update({'count': 0, 'last_reset': now})
                return {'uid': uid, 'data': data, 'is_guest': False}
            else:
                # Initialize new user in Firestore
                new_data = {
                    'count': 0, 
                    'balance': 0.0, 
                    'last_reset': now, 
                    'email': decoded_token.get('email', ''),
                    'name': decoded_token.get('name', 'User')
                }
                user_ref.set(new_data)
                return {'uid': uid, 'data': new_data, 'is_guest': False}
        except Exception as e:
            print(f"FIREBASE AUTH ERROR: {e}")

    # CASE 2: Guest User (IP Based)
    if ip not in user_usage:
        user_usage[ip] = {'count': 0, 'balance': 0.0, 'last_reset': now}
    
    if now - user_usage[ip]['last_reset'] > 86400:
        user_usage[ip] = {'count': 0, 'balance': 0.0, 'last_reset': now}
        
    return {'uid': ip, 'data': user_usage[ip], 'is_guest': True}

def update_user_stats(uid, delta_count, delta_balance, is_guest):
    """Update user stats in Firestore or memory."""
    if not is_guest and FIREBASE_ENABLED:
        try:
            user_ref = db.collection('users').document(uid)
            user_ref.update({
                'count': firestore.Increment(delta_count),
                'balance': firestore.Increment(delta_balance),
                'last_activity': firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            print(f"FIREBASE DB ERROR: {e}")
            # Fallback to memory if DB write fails
            if uid not in user_usage:
                user_usage[uid] = {'count': 0, 'balance': 0.0, 'last_reset': time.time()}
            user_usage[uid]['count'] += delta_count
            user_usage[uid]['balance'] += delta_balance
    else:
        # Update in memory
        if uid not in user_usage:
            user_usage[uid] = {'count': 0, 'balance': 0.0, 'last_reset': time.time()}
        
        user_usage[uid]['count'] += delta_count
        user_usage[uid]['balance'] += delta_balance
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
        print("GITHUB ERROR: GH_TOKEN or GH_REPO not set. Skipping trigger (Local Testing).")
        return "MISSING_TOKEN"

    url = f"https://api.github.com/repos/{repo}/actions/workflows/download.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    # Current Space URL for callback
    space_name = os.environ.get('SPACE_ID', '')
    if space_name:
        callback_url = f"https://{space_name.lower().replace('/', '-')}.hf.space/github-callback?job_id={job_id}"
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

def download_video(url, current_job_id=None):
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
            print(f"Starting local download for {url}...")
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename):
                return "SUCCESS", {
                        'filename': os.path.basename(filename),
                        'title': info.get('title', 'Instagram Video'),
                        'thumbnail': info.get('thumbnail', '')
                    }
    except Exception as e:
        import re
        err_str = str(e)
        clean_err = re.sub(r'\x1b\[.*?m', '', err_str).lower()
        print(f"LOCAL DOWNLOAD FAILED: {err_str}")
        
        # 2. Trigger GitHub Actions if blocked
        if "403" in clean_err or "forbidden" in clean_err or "address associated" in clean_err or "blocked" in clean_err or "empty media" in clean_err or "api is not granting access" in clean_err or "not available" in clean_err:
            if not current_job_id: current_job_id = str(uuid.uuid4())
            job_status[current_job_id] = {'status': 'pending', 'filename': None, 'timestamp': time.time()}
            trigger_result = trigger_github_action(url, current_job_id)
            if trigger_result == True:
                return "PENDING_GITHUB", current_job_id
            elif trigger_result == "MISSING_TOKEN":
                return "PENDING_GITHUB_LOCAL", current_job_id
        
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
    auth_header = request.headers.get('Authorization')
    token = auth_header.split('Bearer ')[1] if auth_header and 'Bearer ' in auth_header else None
    
    user = get_user_data(token_id=token, ip=ip)
    user_data = user['data']
    
    if user_data['count'] >= DAILY_LIMIT:
        return jsonify({'success': False, 'message': f'Daily limit reached ({DAILY_LIMIT} downloads). Login or come back tomorrow!'}), 403

    data = request.json
    url = data.get('url')
    if not url: return jsonify({'success': False, 'message': 'No URL provided'}), 400
    # Extract host_url before thread starts
    host_url = request.host_url
    
    # Generate Job ID and start background thread
    job_id = str(uuid.uuid4())
    job_status[job_id] = {'status': 'pending', 'filename': None, 'timestamp': time.time()}
    
    # Reward for starting a job
    update_user_stats(user['uid'], 1, REWARD_PER_DOWNLOAD, user['is_guest'])

    def run_download_task(target_url, j_id, h_url):
        status, result = download_video(target_url, j_id)
        if status == "SUCCESS":
            raw_thumb = result.get('thumbnail', '')
            try:
                proxy_thumb = f"{h_url}proxy-img?url={raw_thumb}" if raw_thumb else ""
            except:
                proxy_thumb = raw_thumb
            
            job_status[j_id] = {
                'status': 'ready',
                'filename': result['filename'],
                'title': result['title'],
                'thumbnail': proxy_thumb
            }
        elif status == "PENDING_GITHUB" or status == "PENDING_GITHUB_LOCAL":
            job_status[result]['status'] = 'pending'
            
            msg = 'Hugging Face is blocked. Switching to GitHub Backup...'
            if status == "PENDING_GITHUB_LOCAL":
                msg = 'Local Testing: GitHub Trigger skipped due to missing tokens. Simulating pending state...'
                
            job_status[result]['message'] = msg
        else:
            job_status[j_id] = {'status': 'failed', 'message': result}
            
    # Start thread
    import threading
    thread = threading.Thread(target=run_download_task, args=(url, job_id, host_url))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True, 
        'status': 'pending',
        'job_id': job_id,
        'remaining': DAILY_LIMIT - (user_data['count'] + 1),
        'balance': round(user_data['balance'] + REWARD_PER_DOWNLOAD, 2),
        'message': 'Job Created. Pending...'
    })

@app.route('/check-limit', methods=['POST'])
def check_limit():
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    
    ip = get_remote_address()
    auth_header = request.headers.get('Authorization')
    token = auth_header.split('Bearer ')[1] if auth_header and 'Bearer ' in auth_header else None
    
    user = get_user_data(token_id=token, ip=ip)
    user_data = user['data']
    
    return jsonify({
        'usage': user_data['count'],
        'limit': DAILY_LIMIT,
        'remaining': max(0, DAILY_LIMIT - user_data['count']),
        'balance': round(user_data['balance'], 2),
        'is_guest': user['is_guest']
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
        'socket_timeout': 5, # Forces yt-dlp to timeout quickly so UI doesn't hang
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
