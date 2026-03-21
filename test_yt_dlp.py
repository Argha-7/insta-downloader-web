import yt_dlp
import json

def test_extraction(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'no_playlist': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            print(f"SUCCESS: {info.get('title')}")
            print(f"Uploader: {info.get('uploader')}")
            # print(json.dumps(info, indent=2))
    except Exception as e:
        print(f"FAILURE: {e}")

if __name__ == "__main__":
    # Test with a YouTube Short URL
    test_extraction("https://www.youtube.com/shorts/pL_X-Qy-YRE")
    # Test with a regular YouTube URL
    test_extraction("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
