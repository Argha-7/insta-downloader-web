from app import download_video
import json
import os

def verify_professional_mode():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ" # Rick Astley
    print(f"Testing download for: {url}")
    status, result = download_video(url, platform='youtube')
    print(f"Status: {status}")
    if status == "SUCCESS":
        print("RESULT:")
        print(json.dumps(result, indent=2))
        # Check if uploader is 'Pro API'
        if result.get('uploader') == 'Pro API':
            print("VERIFIED: Download used the Professional API!")
        else:
            print("INFO: Download used Local Fallback (yt-dlp)")
    else:
        print(f"FAILED: {result}")

if __name__ == "__main__":
    verify_professional_mode()
