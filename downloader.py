import os
import re
import time
import uuid
import requests
import yt_dlp
from playwright.sync_api import sync_playwright

# Temporary downloads folder in the project directory
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(TEMP_DIR, exist_ok=True)

# PC Downloads folder for saving files that are too large for Telegram
PC_DOWNLOADS_DIR = os.path.join(os.path.expanduser('~'), 'Downloads')
os.makedirs(PC_DOWNLOADS_DIR, exist_ok=True)

def is_tiktok_url(url):
    return 'tiktok.com' in url or 'vt.tiktok.com' in url

def is_youtube_url(url):
    return 'youtube.com' in url or 'youtu.be' in url

def is_facebook_url(url):
    return 'facebook.com' in url or 'fb.watch' in url or 'fb.gg' in url

def sanitize_filename(name):
    """
    Removes invalid characters for Windows filenames.
    """
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r'\s+', " ", name)
    return name.strip()

def clean_str(s):
    """
    Remove surrogate characters from a string so it can safely be
    encoded to UTF-8. Playwright sometimes injects surrogates when
    scraping pages with non-ASCII content (e.g. Khmer, Arabic).
    """
    if not s:
        return s
    return s.encode('utf-8', errors='ignore').decode('utf-8')

def download_direct_url(url, dest_path, progress_callback=None):
    """
    Downloads a direct URL in chunks and updates progress_callback.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    response = requests.get(url, stream=True, headers=headers, timeout=60)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    downloaded_size = 0
    chunk_size = 1024 * 1024  # 1MB
    
    start_time = time.time()
    last_callback_time = 0
    
    with open(dest_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded_size += len(chunk)
                
                percent = (downloaded_size / total_size * 100) if total_size else 0.0
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Speed calculation
                speed_bps = downloaded_size / elapsed if elapsed > 0 else 0
                if speed_bps > 1024 * 1024:
                    speed_str = f"{speed_bps / (1024 * 1024):.1f} MB/s"
                elif speed_bps > 1024:
                    speed_str = f"{speed_bps / 1024:.1f} KB/s"
                else:
                    speed_str = f"{speed_bps:.1f} B/s"
                
                if current_time - last_callback_time >= 2.0 or downloaded_size == total_size:
                    last_callback_time = current_time
                    if progress_callback:
                        progress_callback(percent, speed_str, downloaded_size, total_size)
                        
    return dest_path

def download_tiktok_tikwm(url, format_type, unique_id, progress_callback=None):
    """
    Attempts to download TikTok video/audio without watermark using TikWM API.
    """
    api_url = "https://www.tikwm.com/api/"
    params = {"url": url, "hd": 1}
    
    try:
        response = requests.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        res_data = response.json()
        
        if res_data.get("code") == 0:
            data = res_data["data"]
            title = data.get("title") or f"TikTok_video_{int(time.time())}"
            
            if format_type == 'mp3':
                download_url = data.get("music") or (data.get("music_info", {}).get("play"))
                ext = "mp3"
            else:
                download_url = data.get("play")
                ext = "mp4"
                
            if not download_url:
                return None, "TikTok Video"
                
            dest_file = os.path.join(TEMP_DIR, f"{unique_id}.{ext}")
            download_direct_url(download_url, dest_file, progress_callback)
            return dest_file, title, download_url
            
    except Exception as e:
        print(f"TikWM download failed for {url}: {e}")
        
    return None, "TikTok Video", None

def download_with_ytdl(url, format_type, unique_id, progress_callback=None):
    """
    Downloads media using yt-dlp to temp folder.
    """
    dest_template = os.path.join(TEMP_DIR, f"{unique_id}.%(ext)s")
    
    def ytdl_hook(d):
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', '').strip().replace('%', '')
            try:
                percent = float(percent_str)
            except ValueError:
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                percent = (downloaded / total * 100) if total else 0.0
                
            speed_str = d.get('_speed_str', 'N/A')
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            
            if progress_callback:
                progress_callback(percent, speed_str, downloaded, total)
                
        elif d['status'] == 'finished':
            if progress_callback:
                progress_callback(100.0, "0 B/s", d.get('downloaded_bytes', 0), d.get('total_bytes', 0))

    ydl_opts = {
        'outtmpl': dest_template,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [ytdl_hook],
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android']
            }
        }
    }
    
    if format_type == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
        })
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title") or "Video"
            expected_filename = ydl.prepare_filename(info)
            
            if format_type == 'mp3':
                base, _ = os.path.splitext(expected_filename)
                final_filename = base + ".mp3"
            else:
                base, _ = os.path.splitext(expected_filename)
                final_filename = base + ".mp4"
                
            if os.path.exists(final_filename):
                return final_filename, title, None
            elif os.path.exists(expected_filename):
                return expected_filename, title, None
                
    except Exception as e:
        print(f"yt-dlp download failed: {e}")
        
    return None, "Video", None

def download_media(url, format_type, progress_callback=None):
    """
    Main entry point to download video/audio.
    Returns (file_path, file_size_mb, title, direct_url).
    """
    unique_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    file_path = None
    title = "Video"
    direct_url = None

    # TikTok handling
    if is_tiktok_url(url):
        file_path, title, direct_url = download_tiktok_tikwm(url, format_type, unique_id, progress_callback)

    # Facebook handling via Playwright (browser rendering)
    if not file_path and is_facebook_url(url):
        file_path, title, direct_url = download_facebook_playwright(url, format_type, unique_id, progress_callback)

    # Generic handling via yt-dlp for other URLs
    if not file_path:
        file_path, title, direct_url = download_with_ytdl(url, format_type, unique_id, progress_callback)

    if file_path and os.path.exists(file_path):
        size_bytes = os.path.getsize(file_path)
        size_mb = size_bytes / (1024 * 1024)
        return file_path, size_mb, title, direct_url

    return None, 0.0, "Video", None


def get_direct_url(url, format_type):
    """
    Extract the direct CDN download URL without downloading the full file.
    Returns (direct_url, title) or (None, None) on failure.
    """
    # TikTok via tikwm API
    if is_tiktok_url(url):
        try:
            api_url = "https://www.tikwm.com/api/"
            params = {"url": url, "hd": 1}
            response = requests.get(api_url, params=params, timeout=15)
            response.raise_for_status()
            res_data = response.json()
            if res_data.get("code") == 0:
                data = res_data["data"]
                title = data.get("title") or "TikTok Video"
                if format_type == 'mp3':
                    direct_url = data.get("music") or data.get("music_info", {}).get("play")
                else:
                    direct_url = data.get("play")
                if direct_url:
                    return direct_url, title
        except Exception as e:
            print(f"[get_direct_url] TikTok failed: {e}")

    # Facebook via Playwright
    if is_facebook_url(url):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
                match = re.search(r'"playable_url":"(https:[^"]+)"', html)
                if match:
                    video_url = match.group(1)
                    # Safely decode \uXXXX unicode escapes using regex (avoids surrogate errors)
                    video_url = re.sub(r'\\u([0-9a-fA-F]{4})',
                                       lambda m: chr(int(m.group(1), 16)), video_url)
                    video_url = video_url.replace('\\/', '/')
                else:
                    meta_match = re.search(r'<meta property="og:video" content="(https:[^"]+)"', html)
                    video_url = meta_match.group(1) if meta_match else None
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                title = title_match.group(1) if title_match else "Facebook Video"
                # Strip any surrogate characters from extracted strings
                video_url = clean_str(video_url)
                title = clean_str(title)
                browser.close()
                if video_url:
                    return video_url, title
        except Exception as e:
            print(f"[get_direct_url] Facebook Playwright failed: {e}")

    # Generic via yt-dlp (extract info only, no download)
    try:
        is_mp3 = (format_type == 'mp3')
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best' if is_mp3 else 'best',
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android']
                }
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title") or "Video"
            
            # Verify root url has audio if we want video
            if 'url' in info:
                vcodec = info.get('vcodec')
                acodec = info.get('acodec')
                if is_mp3 or (vcodec != 'none' and acodec != 'none'):
                    return info['url'], title
            
            # Fallback to formats list
            formats = info.get('formats', [])
            if is_mp3:
                # Audio formats
                valid_formats = [f for f in formats if f.get('url') and f.get('acodec') != 'none']
            else:
                # Progressive video formats (both audio and video codecs must not be none)
                valid_formats = [
                    f for f in formats 
                    if f.get('url') and f.get('vcodec') != 'none' and f.get('acodec') != 'none'
                ]
            
            if valid_formats:
                best = valid_formats[-1]
                return best['url'], title
    except Exception as e:
        print(f"[get_direct_url] yt-dlp info failed: {e}")

    return None, None

# Helper for Facebook direct download (no yt-dlp, no cookies)

def download_facebook_direct(url, format_type, unique_id, progress_callback=None):
    """Attempt to download a Facebook video without yt-dlp.
    Currently only supports MP4 (video). MP3 fallback returns the video file.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text
        # Look for "playable_url":"..." pattern in page source
        import re
        match = re.search(r'"playable_url":"(https:[^\"]+)', html)
        if not match:
            # Fallback to og:video meta tag
            meta_match = re.search(r'<meta property="og:video" content="(https:[^"]+)"', html)
            if meta_match:
                video_url = meta_match.group(1)
            else:
                return None, "Facebook Video"
        else:
            video_url = match.group(1).replace('\\/', '/')
        # For mp3 request, we still download video; conversion could be added later
        ext = "mp4"
        dest_file = os.path.join(TEMP_DIR, f"{unique_id}.{ext}")
        download_direct_url(video_url, dest_file, progress_callback)
        # Extract title from page (og:title)
        title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        title = title_match.group(1) if title_match else f"Facebook_video_{unique_id}"
        return dest_file, title, video_url
    except Exception as e:
        print(f"Facebook direct download failed for {url}: {e}")
        return None, "Facebook Video", None

# Use Playwright fallback for Facebook download (headless browser)


def download_facebook_playwright(url, format_type, unique_id, progress_callback=None):
    """Use Playwright to render the Facebook page and extract a video URL.
    This works for pages that require JavaScript to expose the video source.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            html = page.content()
            # Re-use the same regex logic as the direct method
            import re
            match = re.search(r'"playable_url":"(https:[^"]+)"', html)
            if not match:
                # Try to extract video URL from meta tags using plain HTML regex
                # meta_match = re.search(r'\u003cmeta property=\"og:video\" content=\"(https:[^\"]+)\"', html)
                meta_match = re.search(r'<meta property="og:video" content="(https:[^"]+)"', html)
                if meta_match:
                    video_url = meta_match.group(1)
                else:
                    return None, "Facebook Video", None
            else:
                video_url = match.group(1)
                # Safely decode \uXXXX unicode escapes using regex (avoids surrogate errors)
                video_url = re.sub(r'\\u([0-9a-fA-F]{4})',
                                   lambda m: chr(int(m.group(1), 16)), video_url)
                video_url = video_url.replace('\\/', '/')
            ext = "mp4"
            dest_file = os.path.join(TEMP_DIR, f"{unique_id}.{ext}")
            download_direct_url(video_url, dest_file, progress_callback)
            title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            title = title_match.group(1) if title_match else f"Facebook_video_{unique_id}"
            title = clean_str(title)
            video_url = clean_str(video_url)
            return dest_file, title, video_url
    except Exception as e:
        print(f"Facebook Playwright download failed for {url}: {e}")
        return None, "Facebook Video", None
