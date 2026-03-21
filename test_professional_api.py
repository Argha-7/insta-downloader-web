import requests
import json
import sys

def test_api(video_id):
    url = f"https:/""/api.cdnframe.com/api/v5/info/{video_id}"
    headers = {
        "Origin": "https://kelownacontracting.ca",
        "Referer": "https://kelownacontracting.ca/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {r.status_code}")
        data = r.json()
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_api("dQw4w9WgXcQ")
