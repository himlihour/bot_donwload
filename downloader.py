import os
import re
import time
import uuid
import requests
import yt_dlp
import subprocess
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

# Temporary downloads folder in the project directory
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(TEMP_DIR, exist_ok=True)

# PC Downloads folder for saving files that are too large for Telegram
PC_DOWNLOADS_DIR = os.path.join(os.path.expanduser('~'), 'Downloads')
os.makedirs(PC_DOWNLOADS_DIR, exist_ok=True)

COOKIES_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')

# Check if environment variable YOUTUBE_COOKIES is set. If so, write to cookies.txt dynamically
env_cookies = os.getenv("YOUTUBE_COOKIES")
if env_cookies:
    try:
        with open(COOKIES_FILE_PATH, 'w', encoding='utf-8') as f:
            f.write(env_cookies)
        print("[COOKIES] Loaded YouTube cookies from environment variable YOUTUBE_COOKIES.")
    except Exception as e:
        print(f"[COOKIES] Failed to write environment cookies: {e}")

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
    
    if os.path.exists(COOKIES_FILE_PATH):
        ydl_opts['cookiefile'] = COOKIES_FILE_PATH
    
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

def load_netscape_cookies(cookies_file_path):
    """
    Parses a Netscape format cookies file and returns cookies in Playwright's format.
    """
    cookies = []
    try:
        with open(cookies_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) >= 7:
                    domain = parts[0]
                    flag = parts[1]
                    path = parts[2]
                    secure = parts[3].upper() == 'TRUE'
                    try:
                        expires = int(parts[4])
                    except ValueError:
                        expires = None
                    name = parts[5]
                    value = parts[6]
                    
                    cookie = {
                        'name': name,
                        'value': value,
                        'domain': domain,
                        'path': path,
                        'secure': secure
                    }
                    if expires is not None and expires > 0:
                        cookie['expires'] = expires
                    cookies.append(cookie)
    except Exception as e:
        print(f"[COOKIES] Error parsing cookies file: {e}")
    return cookies

def get_youtube_direct_url_playwright(url, format_type):
    """
    Fallback method using Playwright to extract direct URL for YouTube
    when yt-dlp is blocked by PO Token.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            is_mp3 = (format_type == 'mp3')
            if is_mp3:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            else:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
                    viewport={"width": 360, "height": 640},
                    is_mobile=True
                )

            # Load YouTube cookies if available
            if os.path.exists(COOKIES_FILE_PATH):
                pw_cookies = load_netscape_cookies(COOKIES_FILE_PATH)
                if pw_cookies:
                    context.add_cookies(pw_cookies)

            page = context.new_page()
            captured_url = None
            
            def handle_request(request):
                nonlocal captured_url
                req_url = request.url
                if "googlevideo.com/videoplayback" in req_url:
                    parsed = urlparse(req_url)
                    params = parse_qs(parsed.query)
                    mime = params.get('mime', [''])[0]
                    itag = params.get('itag', [''])[0]
                    
                    if is_mp3:
                        if "audio/" in mime:
                            captured_url = req_url
                    else:
                        if itag in ['18', '22'] or ("video/" in mime and "audio" in mime):
                            captured_url = req_url
                        elif not captured_url and "video/mp4" in mime:
                            captured_url = req_url

            page.on("request", handle_request)
            
            mobile_url = url.replace("www.youtube.com", "m.youtube.com") if not is_mp3 else url
            page.goto(mobile_url, wait_until="domcontentloaded", timeout=20000)
            
            try:
                page.wait_for_selector("video", timeout=10000)
                page.evaluate("document.querySelector('video').play()")
            except Exception:
                pass
                
            start_wait = time.time()
            while not captured_url and time.time() - start_wait < 10:
                time.sleep(0.5)
                
            title = page.title()
            for suffix in [" - YouTube", " - YouTube Mobile", " - YouTube Music"]:
                if title.endswith(suffix):
                    title = title[:-len(suffix)]
            title = clean_str(title)
            
            browser.close()
            if captured_url:
                return captured_url, title
    except Exception as e:
        print(f"[Playwright YouTube direct url] failed: {e}")
    return None, None

def download_youtube_playwright(url, format_type, unique_id, progress_callback=None):
    """
    Downloads YouTube video or audio by using Playwright to play the video in a headless
    browser and intercept the decrypted googlevideo.com streaming URLs.
    """
    video_url = None
    audio_url = None
    video_size = 0
    audio_size = 0
    title = "YouTube Video"
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            # Load YouTube cookies if available
            if os.path.exists(COOKIES_FILE_PATH):
                pw_cookies = load_netscape_cookies(COOKIES_FILE_PATH)
                if pw_cookies:
                    context.add_cookies(pw_cookies)

            page = context.new_page()
            
            def handle_request(request):
                nonlocal video_url, audio_url, video_size, audio_size
                req_url = request.url
                if "googlevideo.com/videoplayback" in req_url:
                    parsed = urlparse(req_url)
                    params = parse_qs(parsed.query)
                    mime = params.get('mime', [''])[0]
                    itag = params.get('itag', [''])[0]
                    clen = int(params.get('clen', [0])[0])
                    
                    if "video/" in mime and "audio" not in mime:
                        if clen > video_size:
                            video_url = req_url
                            video_size = clen
                    elif "audio/" in mime:
                        if clen > audio_size:
                            audio_url = req_url
                            audio_size = clen

            page.on("request", handle_request)
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            try:
                page.wait_for_selector("video", timeout=10000)
                page.evaluate("document.querySelector('video').play()")
            except Exception:
                pass
                
            start_wait = time.time()
            if format_type == 'mp3':
                while not audio_url and time.time() - start_wait < 15:
                    time.sleep(0.5)
            else:
                while (not video_url or not audio_url) and time.time() - start_wait < 15:
                    time.sleep(0.5)
                    
            title = page.title()
            for suffix in [" - YouTube", " - YouTube Mobile", " - YouTube Music"]:
                if title.endswith(suffix):
                    title = title[:-len(suffix)]
            title = clean_str(title)
            
            browser.close()
    except Exception as e:
        print(f"[download_youtube_playwright] Playwright interception failed: {e}")
        
    if format_type == 'mp3':
        if not audio_url:
            return None, "YouTube Video", None
            
        temp_audio = os.path.join(TEMP_DIR, f"{unique_id}_temp_audio")
        dest_file = os.path.join(TEMP_DIR, f"{unique_id}.mp3")
        
        try:
            download_direct_url(audio_url, temp_audio, progress_callback)
            if progress_callback:
                progress_callback(99.0, "Converting...", audio_size, audio_size)
                
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_audio,
                "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k",
                dest_file
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(dest_file):
                return dest_file, title, audio_url
        except Exception as e:
            print(f"[download_youtube_playwright] MP3 conversion failed: {e}")
        finally:
            if os.path.exists(temp_audio):
                os.remove(temp_audio)
    else:
        if not video_url or not audio_url:
            prog_url, _ = get_youtube_direct_url_playwright(url, 'mp4')
            if prog_url:
                dest_file = os.path.join(TEMP_DIR, f"{unique_id}.mp4")
                try:
                    download_direct_url(prog_url, dest_file, progress_callback)
                    return dest_file, title, prog_url
                except Exception as e:
                    print(f"[download_youtube_playwright] Progressive fallback failed: {e}")
            return None, "YouTube Video", None
            
        temp_video = os.path.join(TEMP_DIR, f"{unique_id}_temp_video")
        temp_audio = os.path.join(TEMP_DIR, f"{unique_id}_temp_audio")
        dest_file = os.path.join(TEMP_DIR, f"{unique_id}.mp4")
        
        try:
            def video_progress(percent, speed, downloaded, total):
                if progress_callback:
                    progress_callback(percent * 0.70, speed, downloaded, total)
                    
            def audio_progress(percent, speed, downloaded, total):
                if progress_callback:
                    progress_callback(70.0 + (percent * 0.30), speed, downloaded, total)
            
            download_direct_url(video_url, temp_video, video_progress)
            download_direct_url(audio_url, temp_audio, audio_progress)
            
            if progress_callback:
                progress_callback(99.0, "Merging...", video_size + audio_size, video_size + audio_size)
                
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_video, "-i", temp_audio,
                "-c", "copy", "-map", "0:v:0", "-map", "1:a:0",
                "-movflags", "+faststart", dest_file
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(dest_file):
                return dest_file, title, video_url
        except Exception as e:
            print(f"[download_youtube_playwright] Merge failed: {e}")
        finally:
            for temp_f in [temp_video, temp_audio]:
                if os.path.exists(temp_f):
                    os.remove(temp_f)
                    
    return None, "YouTube Video", None

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

    # Fallback for YouTube via Playwright network interception if yt-dlp fails
    if not file_path and is_youtube_url(url):
        print("[FALLBACK] yt-dlp failed for YouTube. Attempting Playwright fallback...")
        file_path, title, direct_url = download_youtube_playwright(url, format_type, unique_id, progress_callback)

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
        if os.path.exists(COOKIES_FILE_PATH):
            ydl_opts['cookiefile'] = COOKIES_FILE_PATH
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

    # Fallback for YouTube via Playwright if yt-dlp fails
    if is_youtube_url(url):
        print("[FALLBACK] yt-dlp get_direct_url failed. Attempting Playwright fallback...")
        pw_url, pw_title = get_youtube_direct_url_playwright(url, format_type)
        if pw_url:
            return pw_url, pw_title

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
