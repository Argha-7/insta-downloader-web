import requests
import json

def extract_professional(url):
    """Standalone version of the professional extraction logic."""
    print(f"Testing professional extraction for: {url}")
    try:
        api_url = f"https:/""/api2.y2mate.tools/api/v1/info?url={url}"
        r = requests.get(api_url, timeout=12, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            data = r.json()
            if data.get('status') == 'success':
                video_data = data.get('data', {})
                formats = video_data.get('formats', [])
                best_url = ""
                for f in formats:
                    if f.get('type') == 'mp4' and f.get('quality') in ['720p', '1080p']:
                        best_url = f.get('url')
                        break
                if not best_url and formats:
                    best_url = formats[0].get('url')
                
                if best_url:
                    print("SUCCESS: Professional API returned a link!")
                    print(f"Title: {video_data.get('title')}")
                    print(f"Link: {best_url[:100]}...")
                    return True
    except Exception as e:
        print(f"Pro API Failed: {e}")
    return False

if __name__ == "__main__":
    extract_professional("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
