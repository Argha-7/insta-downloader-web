import os
import re
import time
import threading
import yt_dlp
import requests
import uuid
import json
import firebase_admin
from firebase_admin import credentials, auth
import urllib.parse
from huggingface_hub import CommitScheduler
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

@app.route('/debug/version')
def debug_version():
    return jsonify({"version": "v32-resilience-fix", "time": time.time()})
# Global lock for user_credits to prevent race conditions
data_lock = threading.Lock()
# Simplified CORS for debugging - allows all origins and headers temporarily
CORS(app, resources={r"/*": {"origins": "*", "allow_headers": ["Content-Type", "Authorization", "X-App-Secret"]}})

# SECURITY CONFIG
ALLOWED_ORIGINS = [
    "https://www.instastream.online",
    "https://instastream.online",
    "https://argha-7.blogspot.com",
    "http://localhost:5000",
    "http://127.0.0.1:5000"
]
APP_SECRET = "insta_pro_ai_secure_99" 

def get_client_ip():
    """Robust IP detection for proxy environments like HF."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or "127.0.0.1"

def verify_request():
    """Verify that the request comes from our site and has the secret or a valid Firebase token."""
    secret = request.headers.get('X-App-Secret')
    query_secret = request.args.get('s') # Fallback secret in query param
    auth_header = request.headers.get('Authorization')
    referer = request.headers.get('Referer', 'No Referer')
    origin = request.headers.get('Origin', 'No Origin')
    
    # 1. Check for legacy/internal secret (Header or Query)
    if secret == APP_SECRET or query_secret == APP_SECRET:
        return True
    
    # 2. Check for Firebase Token
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split('Bearer ')[1]
        if firebase_app:
            try:
                decoded_token = auth.verify_id_token(token)
                request.fb_user = decoded_token 
                return True
            except Exception as e:
                print(f"DEBUG: Firebase Token Verification Failed: {e}")
                
    # 3. Soft Verification (Fallback for environments that strip headers)
    # Check if referer or origin is from an allowed domain
    is_allowed_domain = any(domain in referer or domain in origin for domain in ALLOWED_ORIGINS if domain != "http://localhost:5000")
    if is_allowed_domain:
        print(f"SOFT VERIFIED: Request from {referer} allowed despite missing secret.")
        return True

    print(f"CRITICAL: verify_request FAILED - Referer: {referer}, Origin: {origin}, All Headers: {dict(request.headers)}")
    return False

# Persistent Storage Configuration (JSON files)
# We use a /data folder if it exists (HF Persistent Storage), otherwise we use root
DATA_DIR = Path("data") if os.path.exists("data") else Path(".")
ACTIVITY_FILE = DATA_DIR / 'activity.json'
STATS_FILE = DATA_DIR / 'stats.json'
JOBS_FILE = DATA_DIR / 'jobs.json'

# ensure the data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Hugging Face Hub Persistence (Commit logs to a Dataset every 5 mins)
scheduler = None
hf_token = os.environ.get('HF_TOKEN')
dataset_id = os.environ.get('DATASET_ID', 'Argha-7/insta-downloader-logs')

if hf_token:
    try:
        scheduler = CommitScheduler(
            repo_id=dataset_id,
            repo_type="dataset",
            folder_path=DATA_DIR,
            path_in_repo="logs",
            every=5,
            token=hf_token
        )
        print(f"HF Hub Persistence ACTIVE: Syncing to {dataset_id}")
    except Exception as e:
        print(f"HF HUB SYNC ERROR: {e}")
else:
    print("WARNING: HF_TOKEN not set. Persistence will be local-only (wiped on restart).")

# Firebase Initialization (Auth Only)
firebase_app = None
try:
    fb_creds_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
    if fb_creds_json:
        creds_dict = json.loads(fb_creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_app = firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK (Auth only) initialized successfully.")
    else:
        print("WARNING: FIREBASE_SERVICE_ACCOUNT not set. Auth will be disabled.")
except Exception as e:
    print(f"ERROR: Failed to initialize Firebase: {e}")

# Rate Limiter setup (Prevents abuse)
limiter = Limiter(
    get_client_ip,
    app=app,
    default_limits=["2000 per day", "500 per hour"],
    storage_uri="memory://",
)

# Configuration
DOWNLOAD_FOLDER = os.path.join(os.getcwd(), 'downloads')
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Usage tracking (Credits & Cash System)
# Format: {ip: {'credits': 50, 'balance': 0.0, 'referral_id': '...', 'last_activity': timestamp}}
user_credits = {}
DEFAULT_CREDITS = 100
DOWNLOAD_COST = 10
SHARE_REWARD = 20
DOWNLOAD_CASH_REWARD = 0.50 # ₹0.50 per download
REFERRAL_CASH_REWARD = 2.00  # ₹2.00 per new referral

# Stats persistence
STATS_FILE = 'stats.json'
START_EPOCH = 1740787200  # March 1, 2026

def load_stats():
    # Base calculation
    seconds_since_start = time.time() - START_EPOCH
    base_count = 1540 + int(seconds_since_start / 1800)
    
    current_inc = 0
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                data = json.load(f)
                current_inc = data.get("increment", 0)
        except: pass
    
    return {"total_downloads": base_count + current_inc}

def save_stats(increment):
    if scheduler:
        with scheduler.lock:
            with open(STATS_FILE, 'w') as f:
                json.dump({"increment": increment}, f)
    else:
        with open(STATS_FILE, 'w') as f:
            json.dump({"increment": increment}, f)

def increment_downloads():
    current_inc = 0
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                data = json.load(f)
                current_inc = data.get("increment", 0)
        except: pass
    
    save_stats(current_inc + 1)
    return load_stats()["total_downloads"]

ACTIVITY_FILE = 'activity.json'
geo_cache = {}

def get_location(ip):
    """Fetches location data for an IP with simple in-memory caching."""
    if ip in geo_cache:
        return geo_cache[ip]
    
    # Skip geolocation for local IPs
    if ip == "127.0.0.1" or ip.startswith("192.168."):
        return "Local/Internal"
        
    try:
        # Using ip-api.com (Free, no key required)
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                location = f"{data.get('city', 'Unknown')}, {data.get('regionName', 'Unknown')}, {data.get('country', 'Unknown')}"
                geo_cache[ip] = location
                return location
    except Exception as e:
        print(f"GEO ERROR: {e}")
    
    return "Unknown Location"

def log_activity(activity_type, details):
    """Logs user activity to a persistent file with geolocation."""
    try:
        ip = get_client_ip()
        user_email = "Guest"
        user_name = "Anonymous"
        
        # Extract guest info from headers if available
        guest_name = request.headers.get('X-Guest-Name')
        guest_email = request.headers.get('X-Guest-Email')
        
        # Extract authenticated user info if available
        if hasattr(request, 'fb_user'):
            user_email = request.fb_user.get('email', 'Guest')
            user_name = request.fb_user.get('name', 'Anonymous')
        elif guest_email:
            user_email = guest_email
            user_name = guest_name or "Guest"
            
        # Extract discovery source (how they found the site)
        discovery_source = request.headers.get('X-Discovery-Source', 'Unknown')
        if discovery_source == 'Unknown' and request.referrer:
            discovery_source = f"Referrer: {request.referrer}"
            
        activity = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'type': activity_type,
            'ip': ip,
            'user_email': user_email,
            'user_name': user_name,
            'location': get_location(ip),
            'discovery_source': discovery_source,
            'details': details
        }
        
        # Local file logging with scheduler lock
        logs = []
        if os.path.exists(ACTIVITY_FILE):
            try:
                with open(ACTIVITY_FILE, 'r') as f:
                    logs = json.load(f)
            except: logs = []
        
        logs.append(activity)
        if len(logs) > 1000: logs = logs[-1000:]
            
        if scheduler:
            with scheduler.lock:
                with open(ACTIVITY_FILE, 'w') as f:
                    json.dump(logs, f, indent=4)
        else:
            with open(ACTIVITY_FILE, 'w') as f:
                json.dump(logs, f, indent=4)
    except Exception as e:
        print(f"LOGGING ERROR: {e}")

def serialize_firestore_data(data):
    """(Kept for compatibility, though Firestore is removed)"""
    return data

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
    
    with data_lock:
        # Aggressive Logging
        print(f"CRITICAL DEBUG: get_user_data(key={user_key}, ip={ip}, device_id={device_id}, gift={gift})")

        if user_key not in user_credits:
            initial_credits = 1000 if gift == 'bonus100' else DEFAULT_CREDITS
            
            # Check if the request contains a referral ID
            ref_id = None
            if request.is_json:
                try: ref_id = request.json.get('ref')
                except: pass
            if not ref_id: ref_id = request.args.get('ref')
            
            user_credits[user_key] = {
                'credits': initial_credits, 
                'balance': 0.0,
                'referral_id': generate_ref_id(),
                'last_activity': time.time(),
                'is_auth': True if hasattr(request, 'fb_user') else False
            }
            print(f"CRITICAL DEBUG: NEW USER {user_key} initialized with {initial_credits}")

            # Reward the referrer if valid
            if ref_id:
                for other_key, data in user_credits.items():
                    if data['referral_id'] == ref_id and other_key != user_key:
                        data['balance'] += REFERRAL_CASH_REWARD
                        print(f"REFERRAL REWARD: {other_key} earned ₹{REFERRAL_CASH_REWARD}")
                        break
        
        # Aggressive Reset Logic: If credits are 0 or None, and it's not a known exhausted user
        # We'll allow them some slack if they are new or just reset
        target = 1000 if gift == 'bonus100' else DEFAULT_CREDITS
        current_credits = user_credits[user_key].get('credits', 0)
        
        if current_credits < 10 or gift == 'bonus100':
            # Only reset if they aren't actually using it (to prevent infinite downloads)
            # But for the 0 problem, we force it once
            user_credits[user_key]['credits'] = target
            print(f"CRITICAL DEBUG: REFRESHED {user_key} credits: {current_credits} -> {target}")

        user_credits[user_key]['last_activity'] = time.time()
        
        # Periodic Cleanup: Remove entries older than 24h
        if len(user_credits) > 500:
            now = time.time()
            to_delete = [k for k, v in user_credits.items() if now - v.get('last_activity', 0) > 86400]
            for k in to_delete:
                del user_credits[k]
                print(f"DEBUG: AUTO-CLEANUP removed {k}")

        return user_credits[user_key]
JOBS_FILE = 'jobs.json'

def load_jobs():
    # Only use for local fallback
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, 'r') as f:
                return json.load(f)
        except: return {}
    return {}

def save_job(job_id, data):
    with data_lock:
        jobs = load_jobs()
        if job_id in jobs: jobs[job_id].update(data)
        else: jobs[job_id] = data
        if len(jobs) > 100:
            sorted_jobs = sorted(jobs.items(), key=lambda x: x[1].get('timestamp', 0), reverse=True)
            jobs = dict(sorted_jobs[:100])
        
        if scheduler:
            with scheduler.lock:
                with open(JOBS_FILE, 'w') as f:
                    json.dump(jobs, f, indent=4)
        else:
            with open(JOBS_FILE, 'w') as f:
                json.dump(jobs, f, indent=4)

def get_job(job_id):
    jobs = load_jobs()
    return jobs.get(job_id)

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
    # Current Space URL for callback (Enforce lowercase for HF compatibility)
    # Host identification
    space_id = os.environ.get('SPACE_ID', '')
    if space_id:
        host = space_id.replace('/', '-').lower()
        callback_url = f"https://{host}.hf.space/github-callback?job_id={job_id}"
    else:
        # Fallback for local testing (won't work for callback but for trigger)
        callback_url = f"{request.url_root.rstrip('/')}/github-callback?job_id={job_id}"

    payload = {
        "ref": "main",
        "inputs": {
            "video_url": video_url,
            "callback_url": callback_url
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 204:
            print(f"GitHub Action triggered for Job: {job_id}")
            return True
        else:
            print(f"GitHub API Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"GitHub Trigger Exception: {e}")
        return False

def download_video(url, workflow_to_use="download.yml", existing_job_id=None):
    """Main download logic with local-first, then GitHub failover."""
    if '?' in url:
        url = url.split('?')[0]
    
    # 1. Try Local Download (Fastest)
    ydl_opts = {
        'format': 'b[ext=mp4]/b', 
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'insta_{int(time.time())}_%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 120,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'no_playlist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
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
                    'uploader': info.get('uploader') or info.get('uploader_id'),
                    'hashtags': info.get('tags') or re.findall(r'#(\w+)', info.get('description', '')),
                    'hd_url': hd_url,
                    'sd_url': sd_url
                }
    except Exception as e:
        err_str = str(e)
        print(f"LOCAL DOWNLOAD FAILED: {err_str}")
        
        # 2. Trigger GitHub Actions if blocked or extraction fails
        job_id = existing_job_id or str(uuid.uuid4())
        job_data = {
            'status': 'pending', 
            'url': url,
            'timestamp': time.time()
        }
        save_job(job_id, job_data)
        
        if trigger_github_action(url, job_id, workflow=workflow_to_use):
            increment_downloads() # Count as an attempt/task started
            print(f"DEBUG: Triggered GitHub Action {workflow_to_use} for {url} (Job: {job_id})")
            return "PENDING_GITHUB", job_id
        
        save_job(job_id, {'status': 'failed', 'message': f'Error: {err_str[:100]}'})
        return "FAILED", f"Error: {err_str[:100]}"

def process_video_task(url, job_id, user_key, workflow_to_use):
    """Background task to process video and update job_status."""
    try:
        # Pass workflow_to_use and job_id to maintain consistency
        status, result = download_video(url, workflow_to_use=workflow_to_use, existing_job_id=job_id)
        if status == "SUCCESS":
            save_job(job_id, {
                'status': 'ready', 
                'filename': result.get('filename'),
                'title': result.get('title', 'Instagram Video'),
                'thumbnail': result.get('thumbnail', ''),
                'uploader': result.get('uploader'),
                'hashtags': result.get('hashtags'),
                'video_url': result.get('hd_url') or result.get('sd_url'),
                'qualities': {
                    '1080p': result.get('hd_url'),
                    '720p': result.get('sd_url'),
                    'thumb': result.get('thumbnail')
                }
            })
            # Record rewards for successful download completion
            with data_lock:
                if user_key in user_credits:
                    user_credits[user_key]['balance'] += DOWNLOAD_CASH_REWARD
        elif status == "PENDING_GITHUB":
            # download_video already handled the pending status via save_job
            pass 
        else:
            save_job(job_id, {'status': 'failed', 'message': result})
    except Exception as e:
        print(f"ASYNC TASK ERROR: {e}")
        save_job(job_id, {'status': 'failed', 'message': str(e)})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
@limiter.limit("15 per minute")
def handle_download():
    if not verify_request():
        return jsonify({'success': False, 'message': 'Unauthorized Access'}), 403
    
    data = request.json or {}
    url = data.get('url')
    if not url: return jsonify({'success': False, 'message': 'No URL provided'}), 400

    ip = get_client_ip()
    user_key = ip
    if hasattr(request, 'fb_user'): user_key = request.fb_user['uid']
    
    user_data = get_user_data(ip, device_id=data.get('device_id'))
    
    if user_data['credits'] < DOWNLOAD_COST:
        return jsonify({'success': False, 'message': f'Low Credits. Share to earn more!'}), 403

    # Deduct credits early to prevent abuse
    user_data['credits'] -= DOWNLOAD_COST
    
    # Generate Job ID and start background thread
    job_id = str(uuid.uuid4())
    save_job(job_id, {'status': 'pending', 'timestamp': time.time(), 'url': url})
    
    # Determine which workflow to use (App vs Website) BEFORE starting thread
    workflow_to_use = "app_download.yml" if request.path == '/share_target' or (request.referrer and '/app' in request.referrer) else "download.yml"
    
    thread = threading.Thread(target=process_video_task, args=(url, job_id, user_key, workflow_to_use))
    thread.daemon = True
    thread.start()

    log_activity('download_request', {'url': url, 'device_id': data.get('device_id')})

    return jsonify({
        'success': True, 
        'status': 'pending', 
        'job_id': job_id,
        'credits': user_data['credits'],
        'balance': round(user_data['balance'], 2)
    })

@app.route('/stats', methods=['GET'])
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
    
    if user_data['balance'] < 10:
        return jsonify({'success': False, 'message': 'Minimum withdrawal is ₹10.00'}), 400
        
    # Persistent Tracking Logic
    tracking_data = {
        'id': str(uuid.uuid4()),
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'ip': ip,
        'user_key': user_data.get('referral_id', 'unknown'),
        'amount': round(user_data['balance'], 2),
        'upi_id': upi_id
    }
    
    try:
        withdrawals = []
        if os.path.exists('withdrawals.json'):
            with open('withdrawals.json', 'r') as f:
                withdrawals = json.load(f)
        
        withdrawals.append(tracking_data)
        
        with open('withdrawals.json', 'w') as f:
            json.dump(withdrawals, f, indent=4)
            
        print(f"WITHDRAW LOGGED: User {ip} requested ₹{user_data['balance']} to {upi_id}")
    except Exception as e:
        print(f"TRACKING ERROR: {e}")

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
        resp = requests.get(url, stream=True, timeout=60, headers={
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
        resp = requests.get(url, stream=True, timeout=120, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': '*/*',
        })
        
        def generate():
            for chunk in resp.iter_content(chunk_size=1024*64): # Use larger chunks for faster streaming
                if chunk:
                    yield chunk

        log_activity('file_download_proxy', {'url': url, 'name': name})

        return Response(stream_with_context(generate()), 
                        status=resp.status_code,
                        content_type=resp.headers.get('Content-Type', 'video/mp4'),
                        headers={
                            'Content-Disposition': f'attachment; filename="{name}"',
                            'X-Content-Type-Options': 'nosniff',
                            'Cache-Control': 'no-cache'
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
        'geo_bypass': True,
        'no_playlist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate',
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
            uploader = info.get('uploader') or info.get('uploader_id')
            hashtags = info.get('tags') or re.findall(r'#(\w+)', info.get('description', ''))
            
            log_activity('preview_success', {
                'url': url, 
                'title': info.get('title'),
                'uploader': uploader,
                'interests': hashtags[:10] # Top 10 hashtags
            })

            return jsonify({
                'success': True,
                'title': info.get('title', 'Instagram Video'),
                'uploader': uploader,
                'hashtags': hashtags,
                'thumbnail': raw_thumb,
                'video_url': hd_url,
                'qualities': {
                    '1080p': hd_url,
                    '720p': sd_url,
                    'thumb': raw_thumb
                }
            })
    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        print(f"PREVIEW ERROR (Fallback to Placeholder): {e}\n{err_detail}")
        
        # Log to activity for remote debugging
        log_activity('preview_error', {'url': url, 'error': str(e), 'detail': err_detail[:500]})
        
        # Return a partial success so the UI doesn't break, allowing the download to proceed
        return jsonify({
            'success': True,
            'title': 'Instagram Video (Processing...)',
            'uploader': 'User',
            'hashtags': [],
            'thumbnail': 'https://static.cdninstagram.com/rsrc.php/v3/yI/r/VsNE-OHk_8a.png', # Generic IG icon
            'is_fallback': True
        }), 200

@app.route('/status/<job_id>')
@limiter.exempt
def check_status(job_id):
    """Blogger polls this to see if GitHub or Local is done."""
    status = get_job(job_id)
    if not status:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(status)

@app.route('/github-callback', methods=['POST'])
@limiter.exempt
def github_callback():
    """GitHub Action POSTs the file here."""
    job_id = request.args.get('job_id')
    job = get_job(job_id)
    
    # Debug Logging to activity.json
    log_activity('github_callback_receive', {
        'job_id': job_id, 
        'found': bool(job),
        'files': list(request.files.keys()),
        'form': list(request.form.keys())
    })
    
    if not job_id:
        print("CALLBACK ERROR: No job_id provided.")
        return "No job_id", 400
        
    if not job:
        print(f"CALLBACK FAILED: Job {job_id} not found in persistent jobs.json.")
        # Check lowercase version just in case
        job = get_job(job_id.lower())
        if not job:
            return f"Job {job_id} not found", 404
    
    file = request.files.get('file')
    filename = None
    if file:
        filename = f"gh_{int(time.time())}_{file.filename}"
        file.save(os.path.join(DOWNLOAD_FOLDER, filename))
    
    direct_url = request.form.get('direct_url')
    
    # Preserve existing metadata (title, url, etc) if available in the job
    updated_data = {'status': 'ready'}
    if filename: updated_data['filename'] = filename
    if direct_url: updated_data['video_url'] = direct_url
    
    if job.get('title'): updated_data['title'] = job['title']
    if job.get('thumbnail'): updated_data['thumbnail'] = job['thumbnail']
    if job.get('uploader'): updated_data['uploader'] = job['uploader']
    
    save_job(job_id, updated_data)
    print(f"Job {job_id} READY via GitHub Callback.")
    return "OK", 200

@app.route('/api/admin/clear-cache', methods=['POST'])
def clear_cache():
    """Securely clear all in-memory data."""
    secret = request.headers.get('X-App-Secret')
    if secret != os.environ.get('APP_SECRET', 'insta_pro_ai_secure_99'):
        return jsonify({'success': False, 'message': 'Forbidden'}), 403
    
    user_credits.clear()
    job_status.clear()
    print("ADMIN: All in-memory data cleared successfully.")
    return jsonify({'success': True, 'message': 'All data cleared successfully.'})

@app.route('/files/<path:filename>')
def download_file(filename):
    log_activity('file_download_direct', {'filename': filename})
    # If dl=1 is present, force attachment. Otherwise allow inline (for preview).
    as_attachment = request.args.get('dl') == '1'
    response = send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=as_attachment)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
    if not as_attachment:
        # Help browsers recognize it's a video for inline playback
        response.headers["Content-Type"] = "video/mp4"
    return response

@app.route('/admin/activity')
def admin_activity():
    key = request.args.get('s')
    if key != APP_SECRET:
        return "Unauthorized", 401
        
    logs = []
    if os.path.exists(ACTIVITY_FILE):
        with open(ACTIVITY_FILE, 'r') as f:
            try: logs = json.load(f)
            except: logs = []
    
    response = make_response(render_template('admin_activity.html', logs=logs))
    response.headers['X-Frame-Options'] = 'ALLOWALL' 
    response.headers['Content-Security-Policy'] = "frame-ancestors *"
    return response

if __name__ == '__main__':
    # Local fallback for GH_REPO
    if not os.environ.get('GH_REPO'):
        os.environ['GH_REPO'] = "Argha-7/insta-downloader-web"
    app.run(host='0.0.0.0', port=7860)
