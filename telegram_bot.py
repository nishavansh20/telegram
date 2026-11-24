import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import apihelper
from auto_reel_hijacker import download_video, hijack_video, OUTPUT_DIR, REF_DIR

# Fix write/read socket timeouts for video uploads
apihelper.READ_TIMEOUT = 300
apihelper.CONNECT_TIMEOUT = 60

import datetime
import json

START_TIME = time.time()
PING_COUNT = 0

# Health check & Keepalive server for Render free web service + Cron-job.org
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global PING_COUNT
        PING_COUNT += 1
        uptime_sec = int(time.time() - START_TIME)
        uptime_str = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m {uptime_sec % 60}s"
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        print(f"[CRON PING #{PING_COUNT}] Keepalive ping received at {now_str} | Uptime: {uptime_str} | Path: {self.path}")

        response_data = {
            "status": "pong",
            "message": "🏓 Peak Arena Reel Bot is awake and active!",
            "ping_count": PING_COUNT,
            "uptime": uptime_str,
            "timestamp": now_str
        }

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response_data, indent=2).encode("utf-8"))

    def log_message(self, format, *args):
        pass # Clean stdout handled by do_GET

def start_health_server(port):
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"[*] Render healthcheck server active on port {port}")
    server.serve_forever()

# Get token from environment or config file or prompt
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_token.txt")

token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token and os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        token = f.read().strip()

if not token:
    if not sys.stdin.isatty() or os.environ.get("RENDER"):
        print("[-] Fatal: TELEGRAM_BOT_TOKEN environment variable is required on server.")
        sys.exit(1)
    print("=" * 60)
    print("TELEGRAM BOT SETUP:")
    print("1. Open Telegram and search @BotFather")
    print("2. Send /newbot and get your API Token")
    print("=" * 60)
    token = input("Enter your Telegram Bot Token: ").strip()
    if token:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
    else:
        print("Error: No bot token provided. Exiting.")
        sys.exit(1)

bot = telebot.TeleBot(token)

port_env = os.environ.get("PORT")
if port_env:
    threading.Thread(target=start_health_server, args=(int(port_env),), daemon=True).start()

print(f"[*] Peak Arena Telegram Bot is running! Listening for reels/shorts...")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    help_text = (
        "🎮 *Peak Arena Reel Generator Bot*\n\n"
        "Send me any *Instagram Reel* or *YouTube Shorts* URL,\n"
        "or send an *MP4 video file* directly.\n\n"
        "I will automatically:\n"
        "• Keep original human creator voice & gameplay\n"
        "• Inpaint 'Peak Arena app mein' voice punch\n"
        "• Swap in Peak Arena app screen (₹15 BR Solo, ₹20 CS, UPI cashout)\n"
        "• Send you the finished ready-to-post 9:16 Reel!"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['ping'])
def send_ping(message):
    uptime_sec = int(time.time() - START_TIME)
    uptime_str = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m {uptime_sec % 60}s"
    bot.reply_to(message, f"🏓 *Pong!*\nPeak Arena Bot is online.\nUptime: `{uptime_str}`\nTotal Cron Pings: `{PING_COUNT}`", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text and ("http://" in msg.text or "https://" in msg.text))
def handle_url(message):
    url = message.text.strip()
    status_msg = bot.reply_to(message, "⏳ Downloading reel and processing Peak Arena automation...")

    ts = int(time.time())
    out_name = f"PeakArena_Reel_{message.chat.id}_{ts}.mp4"

    try:
        # Download
        video_path = download_video(url)
        if not video_path or not os.path.exists(video_path):
            bot.edit_message_text("❌ Failed to download video from link. Please check if link is public.", message.chat.id, status_msg.message_id)
            return

        bot.edit_message_text("🎬 Inpainting creator voice & swapping Peak Arena app screen...", message.chat.id, status_msg.message_id)

        # Hijack / Process
        result_path = hijack_video(video_path, output_name=out_name)

        bot.edit_message_text("🚀 Uploading rendered reel...", message.chat.id, status_msg.message_id)

        caption = (
            "🔥 *Peak Arena Viral Reel Ready!*\n\n"
            "🏆 *Solo BR:* ₹15 Entry | ₹12 Per Kill | ₹700 Pool\n"
            "⚔️ *Clash Squad:* ₹20 Entry | ₹35 Win\n"
            "⚡ *Instant UPI Cashout* (PhonePe / GPay / Paytm)\n"
            "🎁 *Promo Code:* `PEAK10` for free ₹10 bonus cash"
        )

        sent = False
        for attempt in range(3):
            try:
                with open(result_path, "rb") as video_file:
                    bot.send_video(
                        message.chat.id,
                        video_file,
                        caption=caption,
                        parse_mode="Markdown",
                        supports_streaming=True,
                        timeout=300
                    )
                sent = True
                break
            except Exception as upload_err:
                print(f"[*] Upload attempt {attempt + 1} error: {upload_err}")
                if attempt < 2:
                    time.sleep(2)

        if sent:
            try:
                bot.delete_message(message.chat.id, status_msg.message_id)
            except Exception:
                pass
            print(f"[+] Successfully sent reel to chat {message.chat.id}")
        else:
            bot.edit_message_text("⚠️ Reel rendered, but Telegram upload timed out. Try again or check network.", message.chat.id, status_msg.message_id)

    except Exception as e:
        print(f"[-] Error: {e}")
        try:
            bot.edit_message_text(f"❌ Error processing reel: {str(e)}", message.chat.id, status_msg.message_id)
        except Exception:
            pass

@bot.message_handler(content_types=['video'])
def handle_video_file(message):
    status_msg = bot.reply_to(message, "⏳ Downloading uploaded video file...")
    ts = int(time.time())
    in_path = os.path.join(REF_DIR, f"tg_input_{message.chat.id}_{ts}.mp4")
    out_name = f"PeakArena_Reel_{message.chat.id}_{ts}.mp4"

    try:
        file_info = bot.get_file(message.video.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(in_path, 'wb') as f:
            f.write(downloaded)

        bot.edit_message_text("🎬 Inpainting creator voice & swapping Peak Arena app screen...", message.chat.id, status_msg.message_id)

        result_path = hijack_video(in_path, output_name=out_name)

        bot.edit_message_text("🚀 Uploading rendered reel...", message.chat.id, status_msg.message_id)

        caption = (
            "🔥 *Peak Arena Viral Reel Ready!*\n\n"
            "🏆 *Solo BR:* ₹15 Entry | ₹12 Per Kill | ₹700 Pool\n"
            "⚔️ *Clash Squad:* ₹20 Entry | ₹35 Win\n"
            "⚡ *Instant UPI Cashout* (PhonePe / GPay / Paytm)\n"
            "🎁 *Promo Code:* `PEAK10` for free ₹10 bonus cash"
        )

        sent = False
        for attempt in range(3):
            try:
                with open(result_path, "rb") as video_file:
                    bot.send_video(
                        message.chat.id,
                        video_file,
                        caption=caption,
                        parse_mode="Markdown",
                        supports_streaming=True,
                        timeout=300
                    )
                sent = True
                break
            except Exception as upload_err:
                print(f"[*] Upload attempt {attempt + 1} error: {upload_err}")
                if attempt < 2:
                    time.sleep(2)

        if sent:
            try:
                bot.delete_message(message.chat.id, status_msg.message_id)
            except Exception:
                pass
            print(f"[+] Successfully sent reel to chat {message.chat.id}")
        else:
            bot.edit_message_text("⚠️ Reel rendered, but Telegram upload timed out. Try again or check network.", message.chat.id, status_msg.message_id)

    except Exception as e:
        print(f"[-] Error: {e}")
        try:
            bot.edit_message_text(f"❌ Error processing reel: {str(e)}", message.chat.id, status_msg.message_id)
        except Exception:
            pass

if __name__ == "__main__":
    bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
