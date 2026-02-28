import yt_dlp
import os

url = "https://www.instagram.com/reel/DVOUKw5Ewai/"
ydl_opts = {
    'format': 'best',
    'outtmpl': 'test_video.%(ext)s',
}

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    print("Download finished!")
except Exception as e:
    print(f"Error: {e}")
