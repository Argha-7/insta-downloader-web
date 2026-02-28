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
    # Sanitize URL or add timeout for production
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, 'insta_%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024, # Limit to 50MB
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.instagram.com/',
        'add_header': [
            'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language: en-US,en;q=0.9',
        ],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return True, os.path.basename(filename)
    except Exception as e:
        return False, "Failed to download. Make sure the URL is public."

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
