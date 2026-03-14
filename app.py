import os
import time
import threading
import yt_dlp
import requests
import uuid
import json
import firebase_admin
from firebase_admin import credentials, auth
import urllib.parse
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
# Simplified CORS for debugging - allows all origins and headers temporarily
CORS(app, resources={r"/*": {"origins": "*", "allow_headers": ["Content-Type", "Authorization", "X-App-Secret"]}})

# SECURITY CONFIG
ALLOWED_ORIGINS = [
    "https://argha-7.blogspot.com",
    "https://www.instastream.online",
    "https://instastream.online",
    "http://localhost:5000",
    "http://127.0.0.1:5000"
]
APP_SECRET = "insta_pro_ai_secure_99" 

def verify_request():
    """Verify that the request comes from our site and has the secret or a valid Firebase token."""
    secret = request.headers.get('X-App-Secret')
    auth_header = request.headers.get('Authorization')
    referer = request.headers.get('Referer', 'No Referer')
    
    print(f"DEBUG: verify_request - Secret: {secret}, Referer: {referer}")
    
    # 1. Check for legacy/internal secret
    if secret == APP_SECRET:
        return True
    
    # 2. Check for Firebase Token
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split('Bearer ')[1]
        if firebase_app:
            try:
                decoded_token = auth.verify_id_token(token)
                request.fb_user = decoded_token # Attach for downstream use
                return True
            except Exception as e:
                print(f"DEBUG: Firebase Token Verification Failed: {e}")
                return False
            
    return False

# Firebase Initialization
firebase_app = None
try:
    fb_creds_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
    if fb_creds_json:
        creds_dict = json.loads(fb_creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_app = firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK initialized successfully.")
    else:
        print("WARNING: FIREBASE_SERVICE_ACCOUNT not set. Auth will be disabled.")
except Exception as e:
    print(f"ERROR: Failed to initialize Firebase: {e}")

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
DEFAULT_CREDITS = 500
DOWNLOAD_COST = 10
SHARE_REWARD = 20
DOWNLOAD_CASH_REWARD = 0.50 # ₹0.50 per download
REFERRAL_CASH_REWARD = 2.00  # ₹2.00 per new referral

# Stats persistence
STATS_FILE = 'stats.json'
START_EPOCH = 1740787200  # March 1, 2026

def load_stats():
    # Base calculation: 1540 + ~50 downloads per day since March 1st
    # Growing smoothly every 5 minutes
    seconds_since_start = time.time() - START_EPOCH
    base_count = 1540 + int(seconds_since_start / 1800) # +1 every 30 mins
    
    current_inc = 0
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                data = json.load(f)
                current_inc = data.get("increment", 0)
        except:
            pass
    
    return {"total_downloads": base_count + current_inc}

def save_stats(increment):
    with open(STATS_FILE, 'w') as f:
        json.dump({"increment": increment}, f)

def increment_downloads():
    # Get current increment
    current_inc = 0
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                data = json.load(f)
                current_inc = data.get("increment", 0)
        except:
            pass
    
    save_stats(current_inc + 1)
    return load_stats()["total_downloads"]

def get_client_ip():
    """Robust IP detection for proxy environments like HF."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or "127.0.0.1"

def generate_ref_id():
    return str(uuid.uuid4())[:8]

def get_user_data(ip, gift=None, device_id=None):
    """Helper to get or initialize user data with multi-layer ID tracking."""
    # Priority: Firebase UID > Device ID > IP Address
    user_key = ip
    if hasattr(request, 'fb_user'):
        user_key = request.fb_user['uid']
    elif device_id:
        user_key = f"did_{device_id}"
    
    # Aggressive Logging
    print(f"DEBUG: get_user_data(key={user_key}, ip={ip}, device_id={device_id}, gift={gift})")

    if user_key not in user_credits:
        initial_credits = 1000 if gift == 'bonus100' else DEFAULT_CREDITS
        
        # Check if the request contains a referral ID
        ref_id = request.json.get('ref') if request.is_json else request.args.get('ref')
        
        user_credits[user_key] = {
            'credits': initial_credits, 
            'balance': 0.0,
            'referral_id': generate_ref_id(),
            'last_activity': time.time(),
            'is_auth': True if hasattr(request, 'fb_user') else False
        }
        print(f"DEBUG: NEW USER {user_key} initialized with {initial_credits}")

        # Reward the referrer if valid
        if ref_id:
            for other_key, data in user_credits.items():
                if data['referral_id'] == ref_id and other_key != user_key:
                    data['balance'] += REFERRAL_CASH_REWARD
                    print(f"REFERRAL REWARD: {other_key} earned ₹{REFERRAL_CASH_REWARD}")
                    break
                    
    # Aggressive Reset Logic: Always check if the user needs more credits
    target = 1000 if gift == 'bonus100' else DEFAULT_CREDITS
    old_credits = user_credits[user_key]['credits']
    
    if old_credits < 50 or gift == 'bonus100':
        user_credits[user_key]['credits'] = target
        print(f"DEBUG: REFRESHED {user_key} credits: {old_credits} -> {target}")

    user_credits[user_key]['last_activity'] = time.time()
    return user_credits[user_key]
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

@app.route('/api/stats')
def get_stats():
    return jsonify(load_stats())

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js')

@app.route('/app')
def mobile_app():
    return render_template('app_pwa.html')

@app.route('/share_target', methods=['GET', 'POST'])
def share_target():
    # Instagram usually sends the link in the 'text' or 'url' fields
    url = request.form.get('url') or request.form.get('text') or request.args.get('url') or request.args.get('text')
    
    if not url:
        return "No link received. Please share a Reel from Instagram.", 400
    
    # Simple extraction of URL if it contains extra text
    import re
    urls = re.findall(r'(https?://\S+)', url)
    if urls:
        target_url = urls[0]
        # Redirect to app page with the URL pre-filled
        return render_template('app_pwa.html', prefill_url=target_url)
    
    return "Invalid link. Please try again.", 400

def trigger_github_action(video_url, job_id, workflow="download.yml"):
    """Triggers the specified GitHub Action workflow."""
    token = os.environ.get('GH_TOKEN')
    repo = os.environ.get('GH_REPO') # e.g., "Argha-7/insta-downloader-web"
    
    if not token or not repo:
        print("GITHUB ERROR: GH_TOKEN or GH_REPO not set in Secrets.")
        return False

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
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
                increment_downloads()
                
                # Quality extraction
                hd_url = ""
                sd_url = ""
                mp4_formats = [f for f in info.get('formats', []) if f.get('ext') == 'mp4' and f.get('vcodec') != 'none']
                if mp4_formats:
                    mp4_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
                    hd_url = mp4_formats[0].get('url', '')
                    sd_formats = [f for f in mp4_formats if f.get('height', 0) <= 720]
                    sd_url = sd_formats[0].get('url', '') if sd_formats else hd_url

                return "SUCCESS", {
                    'filename': os.path.basename(filename),
                    'title': info.get('title', 'Instagram Video'),
                    'thumbnail': info.get('thumbnail', ''),
                    'hd_url': hd_url,
                    'sd_url': sd_url
                }
    except Exception as e:
        err_str = str(e)
        print(f"LOCAL DOWNLOAD FAILED: {err_str}")
        
        # 2. Trigger GitHub Actions if blocked or extraction fails
        # Broadening to trigger on almost any error to ensure reliability
        job_id = str(uuid.uuid4())
        job_status[job_id] = {'status': 'pending', 'filename': None, 'timestamp': time.time()}
        
        # Determine which workflow to use (App vs Website)
        workflow_to_use = "app_download.yml" if request.path == '/share_target' or (request.referrer and '/app' in request.referrer) else "download.yml"
        
        if trigger_github_action(url, job_id, workflow=workflow_to_use):
            increment_downloads() # Count as an attempt/task started
            print(f"DEBUG: Triggered GitHub fallback for {url}")
            return "PENDING_GITHUB", job_id
        
        return "FAILED", f"Error: {err_str[:100]}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
@limiter.limit("15 per minute")
def handle_download():
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    
    data = request.json or {}
    gift = data.get('gift') or request.args.get('gift')
    device_id = data.get('device_id')
    
    ip = get_client_ip()
    user_data = get_user_data(ip, gift=gift, device_id=device_id)
    
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
        # URL encode the raw thumb to prevent & characters from breaking the query param
        encoded_thumb = urllib.parse.quote(raw_thumb) if raw_thumb else ""
        proxy_thumb = f"{request.host_url}proxy-img?url={encoded_thumb}" if raw_thumb else ""
        
        # Extract direct links for qualities
        def get_dl_url(u, ext):
            if not u: return ""
            encoded = urllib.parse.quote(u)
            return f"{request.host_url}dl-proxy?url={encoded}&name=instastream_{ext}"

        # Note: 'result' here comes from download_video which currently only returns filename, title, thumb
        # I should probably update download_video to return all info or just use placeholder qualities if not found
        # Actually, let's keep it simple: if hd_url isn't in result, we use the preview's qualities if available on frontend
        # But for consistency, let's try to get them here too if possible
        
        return jsonify({
            'success': True, 
            'status': 'ready', 
            'filename': result['filename'],
            'title': result['title'],
            'thumbnail': proxy_thumb,
            'credits': user_data['credits'],
            'balance': round(user_data['balance'], 2),
            'video_url': result.get('hd_url') or result.get('sd_url'),
            'qualities': {
                '1080p': get_dl_url(result.get('hd_url'), "1080p.mp4"),
                '720p': get_dl_url(result.get('sd_url'), "720p.mp4"),
                'thumb': get_dl_url(raw_thumb, "thumb.jpg")
            }
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

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify(load_stats())

@app.route('/check-limit', methods=['POST'])
def check_limit():
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    
    data = request.json or {}
    gift = data.get('gift') or request.args.get('gift')
    device_id = data.get('device_id')
    
    ip = get_client_ip()
    user_data = get_user_data(ip, gift=gift, device_id=device_id)
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
    
    data = request.json or {}
    device_id = data.get('device_id')
    ip = get_client_ip()
    user_data = get_user_data(ip, device_id=device_id)
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
        # Only return content and content-type to be safe
        headers = {
            'Content-Type': resp.headers.get('Content-Type', 'image/jpeg'),
            'Cache-Control': 'public, max-age=86400'
        }
        return (resp.content, resp.status_code, headers.items())
    except Exception as e:
        return str(e), 500

from flask import Response, stream_with_context

@app.route('/dl-proxy')
def dl_proxy():
    """Proxies a direct URL and forces download with attachment headers (Streaming)."""
    url = request.args.get('url')
    name = request.args.get('name', 'video.mp4')
    if not url: return "No URL", 400
    try:
        resp = requests.get(url, stream=True, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        })
        
        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                yield chunk

        return Response(stream_with_context(generate()), 
                        status=resp.status_code,
                        content_type=resp.headers.get('Content-Type', 'application/octet-stream'),
                        headers={
                            'Content-Disposition': f'attachment; filename="{name}"',
                            'Cache-Control': 'public, max-age=86400'
                        })
    except Exception as e:
        return str(e), 500

@app.route('/preview', methods=['POST'])
def get_preview():
    """Fetches metadata (title/thumbnail) without downloading."""
    data = request.json or {}
    gift = data.get('gift') or request.args.get('gift')
    device_id = data.get('device_id')
    
    ip = get_client_ip()
    user_data = get_user_data(ip, gift=gift, device_id=device_id)
    
    url = data.get('url')
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
            
            # Extract formats
            formats = info.get('formats', [])
            hd_url = ""
            sd_url = ""
            
            # Instagram usually has simple formats. We'll pick the best and a medium one.
            # Filters for mp4 only for maximum compatibility
            mp4_formats = [f for f in formats if f.get('ext') == 'mp4' and f.get('vcodec') != 'none']
            
            if mp4_formats:
                # Sort by resolution/filesize
                mp4_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
                hd_format = mp4_formats[0]
                hd_url = hd_format.get('url', '')
                
                # Find an SD format (around 720p or lower)
                sd_formats = [f for f in mp4_formats if f.get('height', 0) <= 720]
                if sd_formats:
                    sd_url = sd_formats[0].get('url', '')
                else:
                    sd_url = hd_url # Fallback if only one exists
            
            raw_thumb = info.get('thumbnail', '')
            # URL encode the raw thumb to prevent & characters from breaking the query param
            encoded_thumb = urllib.parse.quote(raw_thumb) if raw_thumb else ""
            proxy_thumb = f"{request.host_url}proxy-img?url={encoded_thumb}" if raw_thumb else ""
            
            video_url = hd_url or info.get('url', '') # Use HD as primary video preview
            
            # Use our proxy for qualities to ensure "Force Download"
            def get_dl_url(u, ext):
                if not u: return ""
                encoded = urllib.parse.quote(u)
                return f"{request.host_url}dl-proxy?url={encoded}&name=instastream_{ext}"

            return jsonify({
                'success': True,
                'title': info.get('title', 'Instagram Video'),
                'thumbnail': proxy_thumb,
                'video_url': video_url,
                'qualities': {
                    '1080p': get_dl_url(hd_url, "1080p.mp4"),
                    '720p': get_dl_url(sd_url, "720p.mp4"),
                    'thumb': get_dl_url(raw_thumb, "thumb.jpg")
                }
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
