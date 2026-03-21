import requests
import json

def test_y2mate_tools(url):
    api_url = f"https:/""/api2.y2mate.tools/api/v1/info?url={url}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    try:
        r = requests.get(api_url, headers=headers, timeout=30)
        print(f"Status: {r.status_code}")
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_y2mate_tools("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
