import yt_dlp
import sys

def test_opts():
    url = "https://www.instagram.com/reel/DVvydT5ARRY/"
    ydl_opts = {
        'nocheckcertificate': True,
        'quiet': True,
    }
    print(f"Testing with opts: {ydl_opts}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("Successfully initialized YoutubeDL with 'nocheckcertificate'")
            # ydl.extract_info(url, download=False) # Don't actually hit IG to avoid blocks during test
    except Exception as e:
        print(f"Error with 'nocheckcertificate': {e}")

    ydl_opts_hyphen = {
        'no_check_certificate': True,
        'quiet': True,
    }
    print(f"\nTesting with opts: {ydl_opts_hyphen}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts_hyphen) as ydl:
            print("Successfully initialized YoutubeDL with 'no_check_certificate'")
    except Exception as e:
        print(f"Error with 'no_check_certificate': {e}")

if __name__ == "__main__":
    test_opts()
