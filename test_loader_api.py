import requests
import re

def test_loader_to(url):
    api_url = f"https:/""/loader.to/api/button/?url={url}&f=720"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(api_url, headers=headers, timeout=30)
        print(f"Status: {r.status_code}")
        # Loader.to returns an iframe or a redirect button. 
        # We need to see if it provides direct links or just a UI.
        print(r.text[:500])
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_loader_to("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
