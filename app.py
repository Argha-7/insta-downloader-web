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
    
    # Very Robust yt-dlp options for local (no ffmpeg) and server
    ydl_opts = {
        # 'b[ext=mp4]/b' guarantees a single file with both video and audio
        # This avoids the "merging formats" error when ffmpeg is missing
        'format': 'b[ext=mp4]/b', 
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, 'insta_%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'max_filesize': 100 * 1024 * 1024,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'source_address': '0.0.0.0', 
        'socket_timeout': 30,
        
        # De-active any post-processing that might need ffmpeg
        'no_post_overwrites': True,
        'writethumbnail': False,
        'write_all_thumbnails': False,
        'postprocessors': [],
        
        # Authentic Headers
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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
        print(f"Processing URL: {url}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Extension check
            if not os.path.exists(filename):
                base = os.path.splitext(filename)[0]
                for ext in ['mp4', 'mkv', 'webm', '3gp']:
                    alt_path = f"{base}.{ext}"
                    if os.path.exists(alt_path):
                        filename = alt_path
                        break
            
            if os.path.exists(filename):
                return True, os.path.basename(filename)
            else:
                return False, "Error: File downloaded but not found on disk."
                
    except Exception as e:
        err_str = str(e)
        print(f"CRITICAL ERROR: {err_str}")
        
        if "ffmpeg" in err_str.lower():
            return False, "Error: FFmpeg is missing. Please install FFmpeg on your PC for HD downloads."
        if "Private" in err_str:
            return False, "This video is Private. We can't download it."
        if "login" in err_str:
            return False, "Instagram is asking for Login. Try again or check the link."
        if "403" in err_str:
            return False, "Instagram is blocking this server IP. Try again later."
        if "address associated" in err_str:
            return False, "Network/DNS Error: Server can't reach Instagram."
            
        return False, f"Download failed: {err_str[:80]}..."

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
