import os
import time
import threading
import yt_dlp
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

# Cleanup task to delete files older than 10 minutes
def cleanup_files():
    while True:
        now = time.time()
        for f in os.listdir(DOWNLOAD_FOLDER):
            file_path = os.path.join(DOWNLOAD_FOLDER, f)
            if os.stat(file_path).st_mtime < now - 600: # 10 minutes
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    print(f"Deleted old file: {f}")
        time.sleep(300) # Run every 5 minutes

# Start cleanup thread
threading.Thread(target=cleanup_files, daemon=True).start()

def download_video(url):
    # Clean the URL to remove UTM parameters
    if '?' in url:
        url = url.split('?')[0]
    
    # Triple-Attempt Strategy: Desktop, Mobile, and Stealth
    attempts = [
        # Attempt 1: Desktop Chrome (Standard)
        {
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'proxy': None,
        },
        # Attempt 2: Mobile Safari (iPhone) - Often has different rate limits
        {
            'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'proxy': None,
        },
        # Attempt 3: Stealth Mode (No Proxy, No DNS cache)
        {
            'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'proxy': None,
        }
    ]

    last_error = ""
    
    for i, config in enumerate(attempts):
        print(f"Download Attempt {i+1} for: {url}")
        
        ydl_opts = {
            'format': 'b[ext=mp4]/b', 
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'insta_{int(time.time())}_%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'max_filesize': 100 * 1024 * 1024,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'socket_timeout': 60, # Increased timeout for slow DNS resolution
            
            'http_headers': {
                'User-Agent': config['user_agent'],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.instagram.com/',
            },
            'extractor_args': {
                'instagram': {
                    'allow_anon_user_id': ['1'],
                }
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Verify file exists (sometimes extension is changed)
                if not os.path.exists(filename):
                    base = os.path.splitext(filename)[0]
                    for ext in ['mp4', 'mkv', 'webm', '3gp']:
                        alt_path = f"{base}.{ext}"
                        if os.path.exists(alt_path):
                            filename = alt_path
                            break
                
                if os.path.exists(filename):
                    print(f"Success on Attempt {i+1}!")
                    return True, os.path.basename(filename)
                    
        except Exception as e:
            last_error = str(e)
            print(f"Attempt {i+1} failed: {last_error}")
            # Wait a second before retrying
            time.sleep(1)
            continue

    # Final error mapping
    print(f"ALL ATTEMPTS FAILED. Final Error: {last_error}")
    
    if "Private" in last_error:
        return False, "This content is Private and cannot be downloaded."
    if "429" in last_error:
        return False, "Instagram is rate-limiting us. Try again in 5 minutes."
    if "403" in last_error or "Forbidden" in last_error:
        return False, "Instagram is blocking this server IP. This happens on Hugging Face sometimes. Try a different link."
    if "address associated" in last_error:
        return False, "Network/DNS Error: Server cannot reach Instagram right now. Please wait 2 minutes."
        
    return False, f"Download failed. Try a different link or wait a few minutes."

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
@limiter.limit("5 per minute") # Max 5 downloads per minute per IP
def handle_download():
    try:
        data = request.json
        url = data.get('url')
        if not url:
            return jsonify({'success': False, 'message': 'No URL provided'}), 400
        
        success, result = download_video(url)
        if success:
            return jsonify({'success': True, 'filename': result})
        else:
            return jsonify({'success': False, 'message': result})
    except Exception as e:
        return jsonify({'success': False, 'message': 'Server error. Try again.'})

@app.route('/files/<path:filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)
