import os
import yt_dlp

def download_instagram_video(url, output_path='.'):
    """
    Downloads an Instagram video using yt-dlp.
    """
    ydl_opts = {
        # 'b[ext=mp4]/b' ensures a single file with both video and audio.
        # This prevents the "merging formats" error when ffmpeg is missing.
        'format': 'b[ext=mp4]/b',
        'outtmpl': os.path.join(output_path, '%(title)s_%(id)s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
        'nocheckcertificate': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"Attempting to download: {url}")
            ydl.download([url])
            print("\nVideo downloaded successfully!")
    except Exception as e:
        print(f"\nAn error occurred: {e}")

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        video_url = sys.argv[1]
        print(f"URL received from arguments: '{video_url}'")
    else:
        # Fallback to input if no argument provided
        video_url = input("Enter Instagram Video URL: ").strip()
        print(f"URL received from input: '{video_url}'")
    
    if video_url:
        download_instagram_video(video_url)
    else:
        print("No URL provided.")
