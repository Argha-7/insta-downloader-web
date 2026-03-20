# Instagram Downloader Maintenance Guide

This document provides technical details for maintaining and troubleshooting the Instagram downloader system.

---

## 🏗️ System Architecture

The system consists of three main components:

1.  **Frontend (Blogger Theme)**: `blogger_theme.xml` handles the UI and initial requests.
2.  **API Layer (Hugging Face Space)**: `app.py` runs a Flask server that performs "Fast Previews" and local downloads.
    - **Hugging Face Hub Persistence**: Data is synced to HF Datasets every 5 minutes.
    - **Admin Dashboard**: Real-time stats and robust country/activity charts.
    - **Resilient extraction**: Improved headers and `yt-dlp` settings.
3.  **Failover Layer (GitHub Actions)**: `.github/workflows/download.yml` runs a worker if the HF Space is blocked by Instagram.

---

## 🌟 Key Features

### 1. Fast Preview
Uses `yt-dlp` on the Hugging Face Space to fetch video metadata and a streamable preview URL. This provides instant feedback to users.

### 2. Job-Based Downloads
Large files are handled via a job system.
- If the Space can download the file, it does so and returns it.
- If the Space is blocked, it triggers a **GitHub Action** to download the file and send it to the user.

### 3. Data Persistence (HF Hub)
We use the `huggingface_hub` `CommitScheduler` to save `activity.json`, `stats.json`, and `jobs.json` to a private Hugging Face Dataset. This ensures data survives Space restarts.

---

## 🛠️ Critical Configurations

### `yt-dlp` Settings
We use several flags to avoid IP blocks:
- `--no-check-certificate`: Ignores SSL errors.
- `--geo-bypass`: Bypasses regional restrictions.
- `User-Agent`: Mimics a modern Chrome browser on Windows 11.

### Environment Variables
- `HF_TOKEN`: Required for data persistence (Write access).
- `DATASET_ID`: HF Dataset ID (e.g., `Argha-7/insta-stats`).
- `GH_TOKEN`: Required for triggering GitHub Actions failover.

---

## 🔍 Troubleshooting

### If Download Fails (Local Error)
Check the `yt-dlp` options in `app.py`. Ensure the `referer` and `User-Agent` headers are up to date.

### If Persistent Data Resets
Verify that `HF_TOKEN` and `DATASET_ID` are correctly set in the Space secrets. Check the Space logs for `HF HUB SYNC ERROR`.

### If GitHub Action Fails
Ensure the secret `GH_TOKEN` is valid and has `repo` and `workflow` permissions. Check if the `.github/workflows/download.yml` has any syntax errors.

---

## 📝 Recent Fixes (v32+)

- **Firebase Migration [REVERTED]**: Switched to HF Hub for a self-contained solution.
- **Admin Dashboard Refactor**: Switched to `DOMContentLoaded` and data attributes for better reliability.
- **GHA Typo**: Fixed `--nocheckcertificate` to `--no-check-certificate`.
- **Ultra-Robust Charts**: Added type checks and error boundaries to the dashboard JS.
