import requests
import json

def test_piped(video_id):
    # Public Piped instances: kavin.rocks, official.il.us.me, etc.
    api_url = f"https:/""/pipedapi.kavin.rocks/streams/{video_id}"
    try:
        r = requests.get(api_url, timeout=30)
        print(f"Status: {r.status_code}")
        data = r.json()
        print(f"Title: {data.get('title')}")
        print(f"Video Streams: {len(data.get('videoStreams', []))}")
        if data.get('videoStreams'):
            print(f"Sample Link: {data['videoStreams'][0].get('url')[:100]}...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_piped("dQw4w9WgXcQ")
