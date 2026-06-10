# 🤖 Telegram Downloader Bot (TikTok, YouTube, Facebook)

This is a premium, high-performance Telegram Bot designed to download video and audio from **TikTok (without watermark)**, **YouTube**, and **Facebook**. 

When you send a link, the bot downloads the media, sends it directly to your Telegram chat (allowing you to save it on your phone or other devices), and cleans up your PC storage.

---

## ✨ Features

- **Only Two Buttons**: Simple format selection:
  - 🎥 **Video (MP4)**: Downloads best quality video.
  - 🎵 **Audio (MP3)**: Automatically extracts audio and converts to MP3 using FFmpeg.
- **Watermark-Free TikTok**: Uses TikWM API for clean downloads, with `yt-dlp` fallback.
- **Live Progress Updates**: Shows download percentage and speed inside Telegram:
  `Downloading... [██████░░░░] 60.0%`
- **10-Minute Timeout Protection**: Solves `'The write operation timed out'` connection aborts by increasing read/write timeouts to 10 minutes.
- **Auto PC Storage Cleanup**: Automatically deletes downloaded temporary files from your PC once the file has been successfully uploaded to Telegram.
- **Smart 50MB Fallback**: If a video exceeds Telegram's 50MB bot upload limit, the bot will automatically rename it with its video title and save it directly in your PC's Windows `Downloads` folder (`C:\Users\MSI\Downloads`), notifying you in the chat.
- **Concurrent Threading**: Processes each request in a background thread so multiple downloads can run concurrently.

---

## 🛠️ Prerequisites

1. **Python 3.8+**: Your system is running **Python 3.10.11**, which is perfect.
2. **FFmpeg**: Required for audio extraction and format merging. (Your system already has **FFmpeg** installed!).

---

## 🚀 Setup & Launch Instructions

### Step 1: Install Dependencies
Open your terminal inside this folder and run:
```bash
pip install -r requirements.txt
```

### Step 2: Configure Telegram Token
Open the `.env` file in this folder and verify your bot token:
```env
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
```

### Step 3: Run the Bot
To start the bot, run:
```bash
python bot.py
```
You should see:
```text
[START] Telegram Downloader Bot is starting...
Press Ctrl+C to stop.
```
Now send a link from your phone or PC, select a format, and verify it downloads and uploads correctly!
