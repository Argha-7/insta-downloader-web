import requests
import json

def test_cobalt_v7(url):
    api_url = "https:/""/api.cobalt.tools/api/json"
    data = {
        "url": url,
        "videoQuality": "720",
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    try:
        r = requests.post(api_url, json=data, headers=headers, timeout=30)
        print(f"Status: {r.status_code}")
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_cobalt_v7("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
