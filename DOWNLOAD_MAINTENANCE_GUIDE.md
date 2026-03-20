# Instagram Downloader: Maintenance & Fix Guide

This document explains how the **Instagram Download and Preview** features work in this project. Use this guide if the features break after new changes or during future AI-assisted development.

---

## 1. Overview of the Architecture

The system consists of three main components:
1. **Frontend (Blogger Theme)**: `blogger_theme.xml` handles the UI and initial requests.
2. **API Layer (Hugging Face Space)**: `app.py` runs a Flask server that performs "Fast Previews" and local downloads.
3. **Failover Layer (GitHub Actions)**: `.github/workflows/download.yml` runs a worker if the HF Space is blocked by Instagram.

---

## 2. Key Features and Logic

### A. Preview Feature (Fast)

- **Location**: `app.py` ( `get_preview()` function ).
- **How it works**: Uses `yt-dlp` with `download=False` to fetch metadata (title, thumbnail, formats).
- **Resilience**: If Instagram blocks the HF Space's IP, it returns a **fallback placeholder** (Generic IG icon) but continues the process so the user can still download.

### B. Download Feature (Local + Failover)
- **Location**: `app.py` ( `download_video()` function ).
- **Logic**:
    1.  **Local Attempt**: Tries to download directly on the HF Space.
    2.  **GitHub Failover**: If the local attempt fails (often due to IP blocking), it triggers a GitHub Action (`download.yml`) to download the video on a fresh GitHub runner IP.

---

## 3. Important Configuration (Don't Break These!)

### yt-dlp Options in Python (`app.py`)

To avoid being blocked by Instagram, `ydl_opts` must include:
1. **SSL Bypass**: `'nocheckcertificate': True`.
2. **Geo Bypass**: `'geo_bypass': True`.
3. **Playlist Disable**: `'no_playlist': True`.
- **User-Agent & Headers**: Must look like a real browser.
```python
'http_headers': {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Sec-Fetch-Mode': 'navigate',
}
```

### GitHub Workflow CLI Flags (`download.yml`)
The command in GitHub Actions **MUST** use hyphens for flags, unlike the Python API:
- **Correct**: `--no-check-certificate`
- **Incorrect**: `--nocheckcertificate` (This will cause an "Unknown Option" error).

Full command template:
`python -m yt_dlp -v "${url}" -f "b[ext=mp4]/b" -o "output/video.%(ext)s" --no-playlist --socket-timeout 60 --no-check-certificate`

---

## 4. Troubleshooting Checklist

When things break, check these in order:
1.  **GitHub Action Logs**: Go to "Actions" → "Download Video" on GitHub. Check for `error: no such option`. This usually means a typo in a flag.
2.  **IP Blocking**: If "Preview" works but "Download" only works after a delay, it means the HF Space is blocked, and the system is successfully failing over to GitHub.
3.  **Outdated yt-dlp**: Instagram updates their API frequently. Ensure `requirements.txt` includes `yt-dlp` and it gets updated.
4.  **Blogger API_BASE**: Ensure the `API_BASE` in the Blogger theme points to the correct Hugging Face Space URL.

---

## 5. Recent Fixes (March 2026)
- **Fixed typo**: Changed `--nocheckcertificate` to `--no-check-certificate` in `download.yml`.
- **Improved Headers**: Added `Sec-Fetch-Mode` and `Accept-Language` to `app.py` to reduce bot detection.
- **Enhanced UA**: Updated User-Agent to Chrome 128.
