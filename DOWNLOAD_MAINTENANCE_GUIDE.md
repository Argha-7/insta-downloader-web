# 🍪 YouTube Download Maintenance Guide

YouTube frequently blocks servers (like GitHub and Hugging Face) by asking them to "Sign in". To bypass this, we use **Browser Cookies**. This guide will show you how to keep your downloader running smoothly.

## 1. How to get your YouTube Cookies
1. Install the **"Get cookies.txt LOCALLY"** extension in your Chrome/Edge browser.
2. Open [YouTube.com](https://www.youtube.com) and make sure you are logged in (or just visit the site).
3. Click the extension icon and click **"Export"** (choose Netscape format).
4. You will get a file named `youtube.com_cookies.txt`.

---

## 2. Fixing "Failover" (GitHub Actions)
If the high-speed download fails on the website, it goes to GitHub. To fix this:
1. Go to your GitHub Repository: `Argha-7/insta-downloader-web`.
2. Go to **Settings** > **Secrets and variables** > **Actions**.
3. Click **New repository secret**.
4. Name: `YT_COOKIES`.
5. Value: Open your `youtube.com_cookies.txt` file, copy EVERYTHING inside, and paste it here.
6. Click **Add secret**.

---

## 3. Fixing "Direct Download" (Admin Panel)
To make the website's internal downloader work:
1. Go to your **Admin Dashboard** (`/admin/activity`).
2. Look for the **"YouTube Cookies"** section.
3. Click **Upload Cookies** and select your `youtube.com_cookies.txt` file.
4. Click **Update**.

---

## 🛠️ Troubleshooting
*   **"Sign in" error persists?** Your cookies might have expired. Simply export a new file and update both GitHub and the Admin Panel.
*   **Is it safe?** Yes, the cookies are stored securely on your private server/GitHub secrets. However, never share this file with anyone else.
