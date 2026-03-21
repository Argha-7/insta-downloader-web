# AI Developer Rules (Multi-Downloader Scaling)

This file is a "Rule Book" for any AI or developer working on this project. The goal is to ensure that adding new downloaders (YouTube, FB, Pinterest, etc.) **NEVER** breaks (hampers) the existing Instagram downloader.

## 🛡️ Rule #1: Modular URL Detection

**NEVER** modify the existing Instagram regex or logic to accommodate a new site. Always add a new "Condition" or "Routing" branch for each platform.

### Standard Template for a New Downloader

```python
# Don't touch Instagram logic. Add a separate block for the new site:
if "instagram.com" in url:
    # Existing IG logic remains untouched
    pass
elif "youtube.com" in url or "youtu.be" in url:
    # New YT specific opts/headers
    pass
```

## 🛠️ Rule #2: Isolation of `ydl_opts`

Different sites have different security (Rate limits, Cookies, Headers). Always create a *clean* `ydl_opts` for new sites instead of forcing them into the Instagram options.

1. **Instagram**: Needs high-quality User-Agents and mobile emulation.
2. **YouTube**: Often needs `nocheckcertificate` and specific formats.
3. **Adult Sites**: Might need `cookies.txt` or special age-gate bypass flags.

## 📊 Rule #3: Unified Logging (Dashboard)

When adding a new downloader, ensure it logs to `activity.json` with a consistent prefix.

- ✅ **Good**: `log_activity('download_request', {'site': 'youtube', ...})`
- ✅ **Good**: `log_activity('download_success', {'site': 'facebook', ...})`
- ❌ **Bad**: `log_activity('yt_done', ...)` (This breaks the dashboard charts!)

**Dashboard Sync**: The Admin Dashboard automatically groups types starting with `download`, `preview`, or `file`. Stick to these prefixes.

## 💾 Rule #4: True Persistence (Hugging Face)

All data MUST be stored in `activity.json`, `stats.json`, and `jobs.json` to be synced with the Hugging Face Dataset.

- **Pull first**: Always ensure `hf_hub_download` is called on startup.
- **Locking**: Use `scheduler.lock` when writing to these files to prevent data corruption during simultaneous downloads.

## 🚀 Deployment Rules

After any change, push to **BOTH** remotes to ensure the Space actually updates:

1. `git push origin main` (GitHub Backup)
2. `git push hf main:main --force` (Live Deployment)

---
*Created on March 21, 2026, to ensure the long-term stability of the Instagram Downloader Core.*
