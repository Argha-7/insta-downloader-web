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
CORS(app)

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

# Status tracking for GitHub Actions polling
# Format: {job_id: {'status': 'pending/ready/failed', 'filename': '...'}}
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
                return "SUCCESS", os.path.basename(filename)
    except Exception as e:
        err_str = str(e)
        print(f"LOCAL DOWNLOAD FAILED: {err_str}")
        
        # 2. Trigger GitHub Actions if blocked
        if "403" in err_str or "Forbidden" in err_str or "address associated" in err_str:
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
    data = request.json
    url = data.get('url')
    if not url: return jsonify({'success': False, 'message': 'No URL provided'}), 400
    
    status, result = download_video(url)
    
    if status == "SUCCESS":
        return jsonify({'success': True, 'status': 'ready', 'filename': result})
    elif status == "PENDING_GITHUB":
        return jsonify({'success': True, 'status': 'pending', 'job_id': result, 'message': 'Hugging Face is blocked. Switching to GitHub Backup...' })
    else:
        return jsonify({'success': False, 'message': result})

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
