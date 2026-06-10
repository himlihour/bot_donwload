import os
import shutil
import re
import uuid
import time
import threading
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
    print("[ERROR] TELEGRAM_BOT_TOKEN is not set in the .env file.")
    print("Please edit your .env file and replace 'YOUR_TELEGRAM_BOT_TOKEN' with your actual bot token.")
    import sys
    sys.exit(1)

# Set global pyTelegramBotAPI timeouts to 10 minutes to prevent write/read connection aborts
telebot.apihelper.READ_TIMEOUT = 600
telebot.apihelper.CONNECT_TIMEOUT = 300

bot = telebot.TeleBot(BOT_TOKEN)

# Import downloader functions and paths
from downloader import download_media, get_direct_url, is_tiktok_url, is_youtube_url, is_facebook_url, PC_DOWNLOADS_DIR, sanitize_filename

class ProgressFileWrapper:
    def __init__(self, file_path, callback):
        self.f = open(file_path, 'rb')
        self.total_size = os.path.getsize(file_path)
        self.bytes_read = 0
        self.callback = callback
        self.last_update_time = 0
        self.mode = 'rb'
        self.name = file_path

    def read(self, size=-1):
        data = self.f.read(size)
        if data:
            self.bytes_read += len(data)
            percent = (self.bytes_read / self.total_size) * 100
            current_time = time.time()
            if current_time - self.last_update_time >= 3.0 or self.bytes_read == self.total_size:
                self.last_update_time = current_time
                self.callback(percent, self.bytes_read, self.total_size)
        return data

    def seek(self, offset, whence=0):
        self.f.seek(offset, whence)
        if offset == 0 and whence == 0:
            self.bytes_read = 0

    def tell(self):
        return self.f.tell()

    def close(self):
        self.f.close()

# In-memory URL cache to bypass Telegram's 64-byte callback data limit
class URLCache:
    def __init__(self, max_size=1000):
        self.cache = {}
        self.keys = []
        self.max_size = max_size
        self.lock = threading.Lock()
        
    def set(self, url):
        with self.lock:
            key = uuid.uuid4().hex[:8]
            self.cache[key] = url
            self.keys.append(key)
            if len(self.keys) > self.max_size:
                oldest_key = self.keys.pop(0)
                self.cache.pop(oldest_key, None)
            return key
            
    def get(self, key):
        with self.lock:
            return self.cache.get(key)

url_cache = URLCache()

# Regex to check if text contains an HTTP link
URL_REGEX = re.compile(r'https?://[^\s]+')

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 <b>កម្មវិធីទាញយកវីដេអូ (All-in-One Downloader)</b>\n\n"
        "សូមផ្ញើតំណភ្ជាប់ (Link) ពី **TikTok**, **YouTube**, ឬ **Facebook** មកខ្ញុំ៖\n\n"
        "🎥 វីដេអូនឹងត្រូវបានទាញយក និងផ្ញើជូនអ្នកដោយផ្ទាល់នៅក្នុង Telegram chat នេះ!\n"
        "🎵 គាំទ្រការបំប្លែងទៅជាឯកសារសំឡេង MP3។\n\n"
        "👉 <i>សូមបិទភ្ជាប់ (Paste) តំណភ្ជាប់នៅខាងក្រោមដើម្បីចាប់ផ្តើម!</i>"
    )
    bot.reply_to(message, welcome_text, parse_mode='HTML')

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text
    urls = URL_REGEX.findall(text)
    
    if not urls:
        return
        
    url = urls[0]
    
    # Save to cache and get a short key
    key = url_cache.set(url)
    
    # Create inline keyboard with 3 options
    markup = InlineKeyboardMarkup()
    btn_tg_mp4 = InlineKeyboardButton("🎥 វីដេអូគុណភាពខ្ពស់ (Telegram)", callback_data=f"tg_mp4|{key}")
    btn_link_mp4 = InlineKeyboardButton("🔗 Browser Link (លឿន / មធ្យម)", callback_data=f"link_mp4|{key}")
    btn_mp3 = InlineKeyboardButton("🎵 ឯកសារសំឡេង (MP3)", callback_data=f"mp3|{key}")
    markup.row(btn_tg_mp4)
    markup.row(btn_link_mp4, btn_mp3)
    
    bot.reply_to(
        message, 
        "❓ <b>សូមជ្រើសរើសទម្រង់ (Format)៖</b>\n\n"
        f"🔗 <code>{url}</code>", 
        reply_markup=markup, 
        parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data = call.data
    
    if '|' not in data:
        return
        
    format_type, key = data.split('|', 1)
    url = url_cache.get(key)
    
    if not url:
        bot.answer_callback_query(call.id, "❌ កំហុស៖ តំណភ្ជាប់ហួសសុពលភាព ឬមិនត្រឹមត្រូវ។")
        bot.edit_message_text("❌ ហួសសុពលភាព។ សូមផ្ញើតំណភ្ជាប់ម្តងទៀត។", chat_id=call.message.chat.id, message_id=call.message.message_id)
        return
        
    # Acknowledge callback immediately
    bot.answer_callback_query(call.id, "កំពុងចាប់ផ្តើម...")
    
    # Edit message to show initialization status
    bot.edit_message_text(
        "⏳ <b>កំពុងចាប់ផ្តើម...</b>\nសូមរង់ចាំ កំពុងស្វែងរកព័ត៌មានវីដេអូ...", 
        chat_id=call.message.chat.id, 
        message_id=call.message.message_id, 
        parse_mode='HTML'
    )
    
    # Route to correct processing function
    if format_type == 'link_mp4':
        target_func = download_and_process_link
    else:
        target_func = download_and_process_media
        
    # Spawn background thread to handle download
    threading.Thread(
        target=target_func, 
        args=(call.message.chat.id, call.message.message_id, url, format_type),
        daemon=True
    ).start()

def download_and_process_media(chat_id, message_id, url, format_type):
    file_path = None
    try:
        format_name = "វីដេអូ (MP4)" if format_type == 'tg_mp4' else "ឯកសារសំឡេង (MP3)"
        actual_format = 'mp4' if format_type == 'tg_mp4' else 'mp3'
        
        # Show fetching status
        bot.edit_message_text(
            f"🔍 <b>[1/3] កំពុងស្វែងរកព័ត៌មានវីដេអូ...</b>\nសូមរង់ចាំ...",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='HTML'
        )
        
        last_edit_time = 0
        
        def progress_callback(percent, speed, downloaded, total):
            nonlocal last_edit_time
            current_time = time.time()
            # Throttle edits to Telegram API (at most once every 3 seconds)
            if current_time - last_edit_time < 3.0 and percent < 100.0:
                return
            last_edit_time = current_time
            
            # Create a nice progress bar
            bar_length = 10
            filled_length = int(round(bar_length * percent / 100))
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            
            size_mb = total / (1024 * 1024) if total else 0
            downloaded_mb = downloaded / (1024 * 1024)
            
            progress_text = (
                f"⏳ <b>[2/3] កំពុងទាញយក {format_name}...</b>\n\n"
                f"<code>[{bar}] {percent:.1f}%</code>\n"
                f"⚡ ល្បឿន៖ {speed}\n"
                f"📦 ទំហំ៖ {downloaded_mb:.1f}MB / {size_mb:.1f}MB"
            )
            
            try:
                bot.edit_message_text(
                    progress_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass

        # Download the media file
        file_path, size_mb, title, direct_url = download_media(url, actual_format, progress_callback)
        
        if not file_path or not os.path.exists(file_path):
            bot.edit_message_text(
                f"❌ <b>ការទាញយកបានបរាជ័យ</b>\n\nមិនអាចទាញយកឯកសារមេឌៀបានទេ។ កំពុងប្តូរទៅស្វែងរកតំណភ្ជាប់ជំនួស...",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )
            # Try link fallback if direct URL is available
            if direct_url:
                download_and_process_link(chat_id, message_id, url, 'link_mp4', direct_url=direct_url, title=title)
            else:
                download_and_process_link(chat_id, message_id, url, 'link_mp4')
            return

        ext = 'mp3' if actual_format == 'mp3' else 'mp4'
        clean_title = sanitize_filename(title)
        if not clean_title:
            clean_title = "media"
        if clean_title.lower().endswith(f".{ext}"):
            clean_title = clean_title[:-len(ext)-1]
            
        # Limit title length to prevent Telegram UI truncation in the middle with '...'
        if len(clean_title) > 40:
            clean_title = clean_title[:40].strip()
        clean_filename = f"{clean_title}.{ext}"

        # Define upload progress callback
        def upload_progress_callback(percent, uploaded, total):
            nonlocal last_edit_time
            current_time = time.time()
            # Throttle edits to Telegram API (at most once every 3 seconds)
            if current_time - last_edit_time < 3.0 and percent < 100.0:
                return
            last_edit_time = current_time
            
            bar_length = 10
            filled_length = int(round(bar_length * percent / 100))
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            
            uploaded_mb = uploaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            
            progress_text = (
                f"📤 <b>[3/3] កំពុងបញ្ជូន {format_name} ទៅកាន់ Telegram...</b>\n\n"
                f"<code>[{bar}] {percent:.1f}%</code>\n"
                f"📦 ទំហំ៖ {uploaded_mb:.1f}MB / {total_mb:.1f}MB"
            )
            
            try:
                bot.edit_message_text(
                    progress_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass

        # If file size is <= 50MB, upload to Telegram
        if size_mb <= 50.0:
            bot.edit_message_text(
                f"📤 <b>[3/3] កំពុងបញ្ជូន {format_name} ទៅកាន់ Telegram...</b>\nសូមរង់ចាំ...",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )
            
            wrapped_file = ProgressFileWrapper(file_path, upload_progress_callback)
            try:
                caption_text = (
                    f"✅ <b>{title}</b>\n\n"
                    f"📋 <b>ឈ្មោះឯកសារសម្រាប់ចម្លង (ចុចលើវាដើម្បីចម្លង)៖</b>\n"
                    f"<code>{clean_filename}</code>\n\n"
                    f"<i>(ប្រសិនបើប្រព័ន្ធរបស់អ្នកបង្ហាញឈ្មោះឯកសារខូច ឬបាត់ស្រៈ សូមចុចចម្លងឈ្មោះខាងលើទៅបិទភ្ជាប់ពេលរក្សាទុក)</i>"
                )
                if actual_format == 'mp3':
                    bot.send_audio(
                        chat_id=chat_id,
                        audio=wrapped_file,
                        title=title,
                        caption=caption_text,
                        parse_mode='HTML',
                        timeout=600
                    )
                else:
                    bot.send_document(
                        chat_id=chat_id,
                        document=wrapped_file,
                        visible_file_name=clean_filename,
                        caption=caption_text,
                        parse_mode='HTML',
                        timeout=600
                    )
            finally:
                wrapped_file.close()
            
            # Delete status message
            try:
                bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass
                
        else:
            # File is > 50MB, save to PC Downloads and provide link
            pc_path = os.path.join(PC_DOWNLOADS_DIR, clean_filename)
            counter = 1
            base, extension = os.path.splitext(pc_path)
            while os.path.exists(pc_path):
                pc_path = f"{base}_{counter}{extension}"
                counter += 1
                
            shutil.move(file_path, pc_path)
            file_path = None # Set to None so finally block doesn't delete it
            
            # Escape & in URL for HTML href
            safe_url = (direct_url or "").replace('&', '&amp;')
            
            if safe_url:
                result_text = (
                    f"⚠️ <b>ឯកសារធំពេកសម្រាប់ Telegram (>50MB)</b>\n\n"
                    f"💾 បានរក្សាទុកក្នុងថត Downloads លើកុំព្យូទ័ររបស់អ្នក៖\n"
                    f"<code>{os.path.basename(pc_path)}</code>\n\n"
                    f"🔗 តំណភ្ជាប់ទាញយកជំនួសពី Browser៖\n"
                    f'<a href="{safe_url}">ទាញយកតាមរយៈ Browser</a>\n\n'
                    f"📋 <b>ឈ្មោះឯកសារ (ចុចលើវាដើម្បីចម្លង)៖</b>\n"
                    f"<code>{os.path.basename(pc_path)}</code>\n\n"
                    f"<i>ចំណាំ៖ ការទាញយកតាម Browser នឹងមានឈ្មោះឯកសារលំនាំដើមរបស់ប្រប្រព័ន្ធ។ អ្នកអាចបិទភ្ជាប់ឈ្មោះដែលបានចម្លងដើម្បីប្តូរឈ្មោះវា។</i>"
                )
            else:
                result_text = (
                    f"⚠️ <b>ឯកសារធំពេកសម្រាប់ Telegram (>50MB)</b>\n\n"
                    f"💾 បានរក្សាទុកក្នុងថត Downloads លើកុំព្យូទ័ររបស់អ្នក៖\n"
                    f"<code>{os.path.basename(pc_path)}</code>"
                )
                
            bot.edit_message_text(
                result_text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML',
                disable_web_page_preview=True
            )

    except Exception as e:
        print(f"Error downloading/uploading for {url}: {e}")
        # Try falling back to link extraction
        try:
            bot.edit_message_text(
                f"❌ <b>ការបញ្ជូនបានបរាជ័យ</b>\n\nមិនអាចបញ្ជូនឯកសារទៅ Telegram បានទេ។ កំពុងប្តូរទៅស្វែងរកតំណភ្ជាប់ជំនួស...",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )
            download_and_process_link(chat_id, message_id, url, 'link_mp4')
        except Exception:
            pass
    finally:
        # Clean up temp file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as ex:
                print(f"Cleanup failed for {file_path}: {ex}")

def download_and_process_link(chat_id, message_id, url, format_type, direct_url=None, title=None):
    try:
        format_name = "វីដេអូ (MP4)"

        if not direct_url:
            bot.edit_message_text(
                f"⏳ <b>កំពុងស្វែងរកតំណភ្ជាប់ផ្ទាល់...</b>\nសូមរង់ចាំ...",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )
            direct_url, title = get_direct_url(url, 'mp4')

        if not direct_url:
            bot.edit_message_text(
                "❌ <b>រកមិនឃើញតំណភ្ជាប់</b>\n\n"
                "មិនអាចស្វែងរកតំណភ្ជាប់ទាញយកផ្ទាល់សម្រាប់វីដេអូនេះទេ។\n"
                "វីដេអូនេះអាចជាវីដេអូឯកជន (Private) ឬត្រូវបានការពារ។",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )
            return

        # Escape & in URL for HTML href
        safe_url = direct_url.replace('&', '&amp;')
        title_display = title or "Video"

        # Generate clean, copyable filename
        ext = 'mp4'
        clean_title = sanitize_filename(title_display)
        if not clean_title:
            clean_title = "media"
        if clean_title.lower().endswith(f".{ext}"):
            clean_title = clean_title[:-len(ext)-1]
        # Limit title length to prevent Telegram UI truncation in the middle with '...'
        if len(clean_title) > 40:
            clean_title = clean_title[:40].strip()
        clean_filename = f"{clean_title}.{ext}"

        result_text = (
            f"✅ <b>{title_display}</b>\n\n"
            f"⬇️ <b>ទម្រង់៖</b> {format_name}\n\n"
            f'🔗 <a href="{safe_url}">ចុចទីនេះដើម្បីបើក និងទាញយកក្នុង Browser</a>\n\n'
            f"📋 <b>ឈ្មោះឯកសារ (ចុចលើវាដើម្បីចម្លង)៖</b>\n"
            f"<code>{clean_filename}</code>\n\n"
            f"<i>ដើម្បីកែឈ្មោះឯកសារកុំឱ្យញ៉េរញ៉ៃ៖\n"
            f"1. ចុចលើឈ្មោះឯកសារខាងលើដើម្បីចម្លង។\n"
            f"2. បើកតំណភ្ជាប់ → ចុច ⋮ (ចំណុច ៣) → ទាញយក (Download)។\n"
            f"3. ចូលទៅកាន់កន្លែងទាញយករបស់ Browser រួចប្តូរឈ្មោះឯកសារ (Rename) ដោយបិទភ្ជាប់ (Paste) ឈ្មោះដែលបានចម្លង។</i>"
        )

        bot.edit_message_text(
            result_text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='HTML',
            disable_web_page_preview=True
        )

    except Exception as e:
        print(f"Error handling link for {url}: {e}")
        try:
            bot.edit_message_text(
                f"❌ <b>កំហុស</b>\n\nមានកំហុសមួយបានកើតឡើង៖ <code>{str(e)}</code>",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )
        except Exception:
            pass

import http.server
import socketserver

def start_dummy_server(port):
    class DummyHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is running!")
            
    def run():
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", port), DummyHandler) as httpd:
            print(f"[RENDER] Dummy server listening on port {port}")
            httpd.serve_forever()
            
    threading.Thread(target=run, daemon=True).start()

if __name__ == '__main__':
    print("[START] Telegram Downloader Bot is starting...")
    print("Press Ctrl+C to stop.")
    
    # Start dummy web server if running on Render (PORT env variable is set)
    render_port = os.getenv("PORT")
    if render_port:
        try:
            start_dummy_server(int(render_port))
        except Exception as e:
            print(f"[WARNING] Failed to start Render dummy server: {e}")
            
    # Use infinity_polling to keep running and automatically retry on connection issues
    bot.infinity_polling(skip_pending=True)
