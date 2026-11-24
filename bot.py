"""
bot.py — Peak Arena Reel Automation Telegram Bot
Supports:
  - Any reel link or direct video upload
  - Multi-turn: collect video → prompt → images → process
  - Freeform edit prompts parsed by Gemini / regex
  - Image attachments for overlay/replacement/bio
  - Voice overlay generation
  - Extend video with new segments
  - Live progress updates (HTML parse mode only)
"""

import os
import re
import time
import html
import uuid
import asyncio
import logging
import imageio_ffmpeg
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

from aiohttp import web

from config import (
    TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, TEMP_DIR, ASSETS_DIR,
    ELEVENLABS_API_KEY, GEMINI_API_KEY, HEALTH_PORT, ENABLE_HEALTH_SERVER
)
from video_processor import download_media, process_reel, apply_edit_instructions
from prompt_parser import parse_edit_prompt
from agy_bridge import agy_bridge

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("PeakArenaReelBot")

URL_REGEX = re.compile(
    r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}"
    r"\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)

# Conversation states
WAITING_PROMPT, COLLECTING_IMAGES, PROCESSING = range(3)

# Per-user state store
USER_INSTA_HANDLES: Dict[int, str] = {}
USER_CUSTOM_VOICES: Dict[int, Path] = {}
CRON_PING_SUBSCRIBERS: Dict[int, int] = {}  # user_id -> interval in minutes
CRON_LAST_PING: Dict[int, float] = {}        # user_id -> timestamp
BOT_START_TIME: float = time.time()

# In-progress session per user: video path + accumulated images + prompt
@dataclass
class Session:
    video_path: Path
    prompt: str = ""
    images: List[Path] = field(default_factory=list)
    mode: str = "custom"   # "custom" = prompt-driven; "peak" = default Peak Arena rebrand


USER_SESSIONS: Dict[int, Session] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_authorized(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def make_status_updater(status_msg, loop):
    """Thread-safe, rate-limited HTML status updater for Telegram."""
    last = [""]
    ts = [0.0]

    def update(*args, **kwargs):
        text = ""
        if args:
            text = str(args[0])
        elif "text" in kwargs:
            text = str(kwargs["text"])
        elif "message" in kwargs:
            text = str(kwargs["message"])
        if not text or text.startswith("MoviePy") or text.startswith("chunk"):
            return
        now = time.time()
        if text == last[0] or ((now - ts[0]) < 2.0 and not text.startswith("\U0001f3ac")):
            return
        last[0] = text
        ts[0] = now
        try:
            asyncio.run_coroutine_threadsafe(
                status_msg.edit_text(text, parse_mode="HTML"), loop
            )
        except Exception:
            try:
                asyncio.run_coroutine_threadsafe(status_msg.edit_text(text), loop)
            except Exception:
                pass

    return update


async def download_tg_file(bot, file_id: str, dest: Path) -> Path:
    f = await bot.get_file(file_id)
    await f.download_to_drive(str(dest))
    return dest


def _split_message(text: str, max_len: int = 4000) -> List[str]:
    """Split long response into Telegram-safe chunks."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_idx = text.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunks.append(text[:split_idx])
        text = text[split_idx:].lstrip()
    return chunks


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = html.escape(update.effective_user.first_name or "")
    await update.message.reply_text(
        f"⚡ <b>Peak Arena &amp; Antigravity (AGY) Agent ready, {name}!</b>\n\n"
        "I act as your remote Antigravity AI interface and video automation studio.\n\n"
        "🤖 <b>Remote AGY Agent:</b>\n"
        "Send any message or task to control Antigravity, run commands, inspect files, and trigger workflows from your phone.\n\n"
        "🎬 <b>Video Automation:</b>\n"
        "• Send any Reel / Short link (or upload a video file)\n"
        "• Auto rebrand for Peak Arena, swap competitor app UI, punch in Hindi voice, or add custom prompts!\n\n"
        "<b>Commands:</b>\n"
        "/status — Check AGY daemon & system health\n"
        "/reset — Clear conversation memory\n"
        "/set_insta @handle — Set default Instagram bio handle\n"
        "/help — Detailed bot guide\n"
        "/cancel — Cancel active session",
        parse_mode="HTML"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 <b>Peak Arena &amp; AGY Remote Bridge Guide</b>\n\n"
        "🤖 <b>Remote AGY Agent:</b>\n"
        "Type any natural language request directly in chat:\n"
        "• <code>What is the current status of the workspace?</code>\n"
        "• <code>Download reel https://... and rebrand it for Peak Arena</code>\n"
        "• <code>List files in output directory</code>\n"
        "• <code>Run git status</code>\n\n"
        "🎬 <b>Video Automation Engine:</b>\n"
        "Send a video or link to launch the interactive editor:\n"
        "• <b>Auto Rebrand:</b> Replaces competitor app UI with Peak Arena UI + bio outro.\n"
        "• <b>Custom Prompts:</b> e.g. <code>Replace app at 5-10s. Add voice 'Download Peak Arena'</code>\n"
        "• <b>Image Attachments:</b> Upload custom app screenshots or logos.\n\n"
        "⚙️ <b>Commands:</b>\n"
        "/status — AGY connection & video output count\n"
        "/reset — Clear AGY conversation memory\n"
        "/set_insta @handle — Set default bio handle\n"
        "/cancel — Cancel current video session\n"
        "/start — Restart",
        parse_mode="HTML"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = agy_bridge.get_status()
    daemon_txt = f"PID {st['daemon_info']['pid']} (port {st['daemon_info']['httpPort']})" if st.get("daemon_info") else "Offline"
    cli_txt = "Available ✅" if st["cli_available"] else "Missing ❌"

    msg = (
        "🌐 <b>Antigravity (AGY) Bridge Status</b>\n\n"
        f"• <b>AGY Runtime:</b> {cli_txt}\n"
        f"• <b>Daemon:</b> {daemon_txt}\n"
        f"• <b>Active Sessions:</b> {st['active_sessions']}\n"
        f"• <b>Output Videos:</b> {st['output_videos_count']}\n"
        f"• <b>Workspace:</b> <code>Peak-Arena-Reel-Automation</code>\n\n"
        "<i>Send any message to chat with AGY or trigger automations!</i>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    agy_bridge.reset_user(uid)
    USER_SESSIONS.pop(uid, None)
    await update.message.reply_text(
        "🔄 <b>Session reset!</b> Started a fresh AGY conversation context.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Instant keepalive ping & diagnostic report."""
    uptime_sec = int(time.time() - BOT_START_TIME)
    hours, rem = divmod(uptime_sec, 3600)
    mins, secs = divmod(rem, 60)
    agy_st = agy_bridge.get_status()
    daemon_txt = "Online ✅" if agy_st["cli_available"] and agy_st.get("daemon_info") else "Offline ⚠️"

    reply = (
        "🏓 <b>Pong!</b>\n\n"
        f"• <b>Uptime:</b> {hours}h {mins}m {secs}s\n"
        f"• <b>AGY Runtime:</b> {daemon_txt}\n"
        f"• <b>Active Daemon:</b> PID {agy_st.get('daemon_info', {}).get('pid', 'N/A')}\n"
        f"• <b>Health Endpoint:</b> <code>http://0.0.0.0:{HEALTH_PORT}/health</code>\n"
        "• <b>Status:</b> 24/7 Active &amp; Ready"
    )
    await update.message.reply_text(reply, parse_mode="HTML")


async def cron_ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable or disable recurring cron ping messages directly to Telegram."""
    uid = update.effective_user.id
    if not context.args:
        interval = CRON_PING_SUBSCRIBERS.get(uid)
        status_txt = f"Active (every {interval} min)" if interval else "Disabled"
        await update.message.reply_text(
            f"⏱️ <b>Cron Ping Status:</b> {status_txt}\n\n"
            "<b>Usage:</b>\n"
            "• <code>/cron_ping 60</code> — Ping me every 60 minutes\n"
            "• <code>/cron_ping 15</code> — Ping me every 15 minutes\n"
            "• <code>/cron_ping off</code> — Turn off recurring pings\n"
            "• <code>/ping</code> — Instant one-off ping",
            parse_mode="HTML"
        )
        return

    arg = context.args[0].lower().strip()
    if arg in ("off", "stop", "disable", "0"):
        CRON_PING_SUBSCRIBERS.pop(uid, None)
        CRON_LAST_PING.pop(uid, None)
        await update.message.reply_text("⏹️ <b>Cron ping notifications disabled.</b>", parse_mode="HTML")
        return

    if not arg.isdigit() or int(arg) < 1:
        await update.message.reply_text("❌ Please provide a positive number of minutes, e.g. <code>/cron_ping 60</code>", parse_mode="HTML")
        return

    mins = int(arg)
    CRON_PING_SUBSCRIBERS[uid] = mins
    CRON_LAST_PING[uid] = time.time()
    await update.message.reply_text(
        f"✅ <b>Cron ping active!</b> You will receive a keepalive ping every <b>{mins} minutes</b>.",
        parse_mode="HTML"
    )


async def set_insta_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/set_insta @_maxeddd</code>", parse_mode="HTML"
        )
        return
    handle = context.args[0].strip()
    if not handle.startswith("@"):
        handle = f"@{handle}"
    USER_INSTA_HANDLES[update.effective_user.id] = handle
    await update.message.reply_text(
        f"&#9989; Default bio handle set to <b>{html.escape(handle)}</b>",
        parse_mode="HTML"
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    USER_SESSIONS.pop(uid, None)
    await update.message.reply_text(
        "&#10060; Session cancelled. Send a new video or link to start again.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Step 1: Receive video (link or file upload)
# ---------------------------------------------------------------------------

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("&#9940; Not authorized.")
        return ConversationHandler.END

    text = update.message.text or ""
    video = update.message.video or update.message.document
    caption = update.message.caption or ""

    status = await update.message.reply_text("&#9203; <b>Receiving video...</b>", parse_mode="HTML")

    try:
        TEMP_DIR.mkdir(exist_ok=True)

        if video:
            raw = TEMP_DIR / f"upload_{uid}_{uuid.uuid4().hex[:6]}.mp4"
            await download_tg_file(context.bot, video.file_id, raw)
            await status.delete()
            session = Session(video_path=raw, prompt=caption)

        else:
            url_m = URL_REGEX.search(text)
            if not url_m:
                await status.delete()
                await update.message.reply_text(
                    "Send a Reel/Short URL or upload a video file.",
                    parse_mode="HTML"
                )
                return ConversationHandler.END

            url = url_m.group(0)
            await status.edit_text("&#9203; <b>Downloading reel...</b>", parse_mode="HTML")

            loop = asyncio.get_running_loop()
            dummy_cb = lambda t: None
            raw = await asyncio.to_thread(download_media, url, dummy_cb)
            await status.delete()

            # Prompt hint in the message after "|"
            prompt_hint = text.split("|", 1)[1].strip() if "|" in text else ""
            session = Session(video_path=raw, prompt=prompt_hint)

        USER_SESSIONS[uid] = session

        # If caption/prompt already given, skip to image collection
        if session.prompt.strip():
            await update.message.reply_text(
                f"&#9989; <b>Video ready!</b>\n\n"
                f"Prompt received: <code>{html.escape(session.prompt)}</code>\n\n"
                "Now send any <b>replacement images</b> (one by one), then send <b>DONE</b> to start editing.\n"
                "Or send <b>DONE</b> now if no images needed.",
                parse_mode="HTML"
            )
            return COLLECTING_IMAGES

        choices_keyboard = ReplyKeyboardMarkup(
            [
                ["⚡ Auto Peak Arena Rebrand", "🤖 Send to AGY Agent"],
                ["✍️ Custom Prompt & Replacements", "❌ Cancel"]
            ],
            one_time_keyboard=True,
            resize_keyboard=True
        )

        await update.message.reply_text(
            "&#9989; <b>Video received! Choose how to edit:</b>\n\n"
            "1&#65039;&#8419; <b>Auto Peak Arena Rebrand:</b>\n"
            "Automatically detects competitor app screens &amp; bio, replaces them with Peak Arena UI, shield logo, and bio.\n\n"
            "2&#65039;&#8419; <b>Custom Prompt &amp; Replacements:</b>\n"
            "Type custom instructions (e.g. replace screens, add your own images, voice overlays, or extend video).\n\n"
            "<i>Click a button below or type your choice:</i>",
            parse_mode="HTML",
            reply_markup=choices_keyboard
        )
        return WAITING_PROMPT

    except Exception as e:
        logger.error(f"receive_video error: {e}", exc_info=True)
        try:
            await status.edit_text(f"&#10060; Error: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        except Exception:
            pass
        return ConversationHandler.END


# ---------------------------------------------------------------------------
# Step 2: Receive prompt
# ---------------------------------------------------------------------------

async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = USER_SESSIONS.get(uid)
    if not session:
        await update.message.reply_text("No active session. Send a video first.")
        return ConversationHandler.END

    text = (update.message.text or "").strip()

    if "CANCEL" in text.upper():
        USER_SESSIONS.pop(uid, None)
        await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if "AGY" in text.upper() or "AGENT" in text.upper() or text in ("3", "3️⃣"):
        session = USER_SESSIONS.pop(uid, None)
        status_msg = await update.message.reply_text(
            "🤖 <b>Handing off video to Antigravity Agent...</b>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        loop = asyncio.get_running_loop()
        updater = make_status_updater(status_msg, loop)

        agent_prompt = (
            f"I have received a video at: {session.video_path.resolve()}.\n"
            "Please analyze and apply Peak Arena branding (competitor app replacement, shield logo watermark, and bio outro for @_maxeddd) or requested edits."
        )
        if session.prompt:
            agent_prompt += f"\nUser instructions: {session.prompt}"

        try:
            answer, videos = await agy_bridge.ask_agent(
                user_id=uid,
                prompt=agent_prompt,
                attached_files=[session.video_path] + session.images,
                status_callback=updater
            )
            try:
                await status_msg.delete()
            except Exception:
                pass

            for chunk in _split_message(answer):
                try:
                    await update.message.reply_text(chunk, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(chunk)

            for vid in videos:
                if vid.exists() and vid.stat().st_size > 0:
                    with open(vid, "rb") as f:
                        await update.message.reply_video(
                            video=f,
                            caption=f"🎬 <b>Peak Arena Video Ready!</b>\n<code>{vid.name}</code>",
                            parse_mode="HTML",
                            write_timeout=180
                        )
        except Exception as e:
            logger.error(f"AGY handoff error: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ Error: {html.escape(str(e))}")

        return ConversationHandler.END

    if "AUTO PEAK ARENA" in text.upper() or text.upper() in ("1", "1️⃣", "DEFAULT", "AUTO", "REBRAND"):
        session.mode = "peak"
        session.prompt = "DEFAULT"
        await update.message.reply_text(
            "⚡ <b>Auto Peak Arena Rebrand selected!</b>\n\nStarting render now...",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        return await _start_processing(update, context)

    if "CUSTOM PROMPT" in text.upper() or text.upper() in ("2", "2️⃣", "CUSTOM", "PROMPT"):
        await update.message.reply_text(
            "✍️ <b>Please type your edit prompt:</b>\n\n"
            "<i>Example:</i>\n"
            "<code>Replace app at 6-11s with my screenshot. Show bio at end. Add voice 'Peak Arena download karo'.</code>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_PROMPT

    # Any other text is treated as custom prompt!
    session.mode = "custom"
    session.prompt = text

    done_keyboard = ReplyKeyboardMarkup([["DONE"], ["❌ Cancel"]], resize_keyboard=True)
    await update.message.reply_text(
        f"&#9989; <b>Prompt saved:</b>\n<code>{html.escape(session.prompt)}</code>\n\n"
        "Now send any <b>replacement images</b> (photos/files).\n"
        "When finished, click or send <b>DONE</b> to start rendering!",
        parse_mode="HTML",
        reply_markup=done_keyboard
    )
    return COLLECTING_IMAGES


# ---------------------------------------------------------------------------
# Step 3: Collect images
# ---------------------------------------------------------------------------

async def collect_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = USER_SESSIONS.get(uid)
    if not session:
        await update.message.reply_text("No active session. Send a video first.")
        return ConversationHandler.END

    # Check text trigger
    text = (update.message.text or "").strip().upper()
    if text in ("DONE", "AUTO", "START") or "AUTO PEAK ARENA" in text or "REBRAND" in text:
        return await _start_processing(update, context)

    # Accept photo or document
    photo = update.message.photo
    doc = update.message.document
    img_file_id = None

    if photo:
        img_file_id = photo[-1].file_id  # highest resolution
    elif doc and doc.mime_type and doc.mime_type.startswith("image/"):
        img_file_id = doc.file_id

    if img_file_id:
        TEMP_DIR.mkdir(exist_ok=True)
        idx = len(session.images)
        dest = TEMP_DIR / f"img_{uid}_{idx}_{uuid.uuid4().hex[:6]}.png"
        await download_tg_file(context.bot, img_file_id, dest)
        session.images.append(dest)
        await update.message.reply_text(
            f"&#128247; Image {idx + 1} saved. Send more images or send <b>DONE</b> to start.",
            parse_mode="HTML"
        )
    elif update.message.text:
        await update.message.reply_text(
            "Send images as photos/files, or type <b>DONE</b> to start editing.",
            parse_mode="HTML"
        )

    return COLLECTING_IMAGES


# ---------------------------------------------------------------------------
# Step 4: Process & render
# ---------------------------------------------------------------------------

async def _start_processing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = USER_SESSIONS.pop(uid, None)
    if not session:
        await update.message.reply_text("No active session.")
        return ConversationHandler.END

    insta_handle = USER_INSTA_HANDLES.get(uid, "@_maxeddd")
    custom_voice = USER_CUSTOM_VOICES.get(uid)
    loop = asyncio.get_running_loop()

    img_count = len(session.images)
    status_msg = await update.message.reply_text(
        f"&#127909; <b>Starting edit...</b>\n"
        f"Prompt: <code>{html.escape(session.prompt[:120])}</code>\n"
        f"Images: {img_count}",
        parse_mode="HTML"
    )
    updater = make_status_updater(status_msg, loop)

    try:
        if session.mode == "peak" or session.prompt.upper() == "DEFAULT":
            # --- Default Peak Arena rebrand pipeline ---
            final_mp4 = await asyncio.to_thread(
                process_reel,
                video_path=session.video_path,
                app_overlay_range=None,
                replace_bio=True,
                insta_handle=insta_handle,
                custom_voice_path=custom_voice,
                audio_replace_range=None,
                elevenlabs_api_key=ELEVENLABS_API_KEY,
                progress_callback=updater,
            )
        else:
            # --- Custom prompt-driven edit pipeline ---
            updater("&#129302; <b>Parsing your edit instructions...</b>")

            # Resolve image paths relative to TEMP_DIR for the parser
            img_names = [str(p) for p in session.images]

            instructions = await asyncio.to_thread(
                parse_edit_prompt,
                session.prompt,
                img_names,
                GEMINI_API_KEY,
            )

            # Inject user-supplied image paths in order
            img_queue = list(session.images)
            for instr in instructions:
                if instr.image_path is not None:
                    # Try to match filename
                    fname = Path(instr.image_path).name
                    matched = next((p for p in img_queue if p.name == fname), None)
                    if matched:
                        instr.image_path = matched
                        img_queue.remove(matched)
                    elif img_queue:
                        instr.image_path = img_queue.pop(0)

            if not instructions:
                await status_msg.edit_text(
                    "&#9888; Could not parse any edits from your prompt. "
                    "Try being more specific, or type DEFAULT for automatic rebrand.",
                    parse_mode="HTML"
                )
                return ConversationHandler.END

            final_mp4 = await asyncio.to_thread(
                apply_edit_instructions,
                session.video_path,
                instructions,
                None,
                updater,
            )

        try:
            await status_msg.edit_text(
                "🚀 <b>Render complete! Uploading...</b>", parse_mode="HTML"
            )
        except Exception:
            pass

        safe_handle = html.escape(insta_handle)
        caption = (
            "&#9989; <b>Peak Arena Reel Ready!</b>\n\n"
            f"&#128279; Bio: {safe_handle}\n"
            "&#127897; Voice: Original preserved\n\n"
            "&#127991; #PeakArena #FreeFireIndia #BGMI #EsportsTournament"
        )
        with open(final_mp4, "rb") as f:
            await update.message.reply_video(
                video=f, caption=caption, parse_mode="HTML", write_timeout=180
            )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)
        safe_e = html.escape(str(e))
        try:
            await status_msg.edit_text(f"&#10060; Error: <code>{safe_e}</code>", parse_mode="HTML")
        except Exception:
            await update.message.reply_text(f"Error: {str(e)}")

    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Voice note handler (outside conversation — usable anytime)
# ---------------------------------------------------------------------------

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    voice = update.message.voice
    if not voice:
        return

    TEMP_DIR.mkdir(exist_ok=True)
    ogg = TEMP_DIR / f"voice_{uid}.ogg"
    wav = TEMP_DIR / f"voice_{uid}.wav"
    await download_tg_file(context.bot, voice.file_id, ogg)

    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(ogg),
         "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(wav)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    USER_CUSTOM_VOICES[uid] = wav
    await update.message.reply_text(
        "&#127897; <b>Voice note saved!</b> Your real voice will be used for voice punch-in.",
        parse_mode="HTML"
    )


# ---------------------------------------------------------------------------
# AGY Agent Remote Interface Handlers
# ---------------------------------------------------------------------------

async def handle_agy_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route natural language messages directly to Antigravity Agent."""
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Not authorized.")
        return

    text = (update.message.text or "").strip()
    if text.startswith("/agy"):
        text = text.replace("/agy", "", 1).strip()
    if not text:
        await update.message.reply_text("Usage: <code>/agy your question or task</code>", parse_mode="HTML")
        return

    status_msg = await update.message.reply_text("🤖 <b>Antigravity Agent processing...</b>", parse_mode="HTML")
    loop = asyncio.get_running_loop()
    updater = make_status_updater(status_msg, loop)

    try:
        answer, videos = await agy_bridge.ask_agent(
            user_id=uid,
            prompt=text,
            status_callback=updater
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

        for chunk in _split_message(answer):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                try:
                    await update.message.reply_text(chunk, parse_mode="HTML")
                except Exception:
                    await update.message.reply_text(chunk)

        for vid in videos:
            if vid.exists() and vid.stat().st_size > 0:
                with open(vid, "rb") as f:
                    await update.message.reply_video(
                        video=f,
                        caption=f"🎬 <b>Peak Arena Video Ready!</b>\n<code>{vid.name}</code>",
                        parse_mode="HTML",
                        write_timeout=180
                    )

    except Exception as e:
        logger.error(f"AGY Agent error: {e}", exc_info=True)
        safe_e = html.escape(str(e))
        try:
            await status_msg.edit_text(f"❌ <b>AGY Error:</b> <code>{safe_e}</code>", parse_mode="HTML")
        except Exception:
            await update.message.reply_text(f"❌ Error: {str(e)}")


async def handle_agy_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download photo and hand off to AGY Agent."""
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Not authorized.")
        return

    photo = update.message.photo[-1]
    caption = (update.message.caption or "Analyze and describe this image.").strip()

    TEMP_DIR.mkdir(exist_ok=True)
    dest = TEMP_DIR / f"tg_photo_{uid}_{uuid.uuid4().hex[:6]}.png"
    await download_tg_file(context.bot, photo.file_id, dest)

    status_msg = await update.message.reply_text("🤖 <b>Processing image with AGY Agent...</b>", parse_mode="HTML")
    loop = asyncio.get_running_loop()
    updater = make_status_updater(status_msg, loop)

    try:
        answer, videos = await agy_bridge.ask_agent(
            user_id=uid,
            prompt=caption,
            attached_files=[dest],
            status_callback=updater
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

        for chunk in _split_message(answer):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)

        for vid in videos:
            if vid.exists() and vid.stat().st_size > 0:
                with open(vid, "rb") as f:
                    await update.message.reply_video(
                        video=f,
                        caption=f"🎬 <b>Peak Arena Video Ready!</b>\n<code>{vid.name}</code>",
                        parse_mode="HTML",
                        write_timeout=180
                    )

    except Exception as e:
        logger.error(f"AGY Photo error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {html.escape(str(e))}")


# ---------------------------------------------------------------------------
# Background 24/7 Tasks: Cron Ping Loop & HTTP Health Server
# ---------------------------------------------------------------------------

async def run_cron_loop(bot):
    """Background loop checking and dispatching recurring cron pings."""
    while True:
        try:
            await asyncio.sleep(20)
            now = time.time()
            for uid, interval_min in list(CRON_PING_SUBSCRIBERS.items()):
                last_ts = CRON_LAST_PING.get(uid, 0.0)
                if now - last_ts >= interval_min * 60:
                    CRON_LAST_PING[uid] = now
                    uptime_sec = int(now - BOT_START_TIME)
                    hours, rem = divmod(uptime_sec, 3600)
                    mins, _ = divmod(rem, 60)
                    agy_st = agy_bridge.get_status()
                    daemon_txt = "Online ✅" if agy_st["cli_available"] else "Offline ⚠️"

                    await bot.send_message(
                        chat_id=uid,
                        text=(
                            f"🏓 <b>[Cron Keepalive Ping]</b>\n"
                            f"• Bot running 24/7 (Uptime: {hours}h {mins}m)\n"
                            f"• AGY Daemon: {daemon_txt}\n"
                            f"• Output Videos: {agy_st['output_videos_count']}"
                        ),
                        parse_mode="HTML"
                    )
        except Exception as e:
            logger.warning(f"Cron loop notice: {e}")


async def on_bot_startup(application):
    """Initialize background HTTP healthcheck server & cron ping loop."""
    # Start cron ping loop
    asyncio.create_task(run_cron_loop(application.bot))

    # Start HTTP health endpoint (keeps free cloud hosting alive)
    if ENABLE_HEALTH_SERVER:
        try:
            server = web.Application()

            async def ping_handler(request):
                uptime_sec = int(time.time() - BOT_START_TIME)
                agy_st = agy_bridge.get_status()
                return web.json_response({
                    "status": "ok",
                    "message": "pong",
                    "uptime_seconds": uptime_sec,
                    "agy_online": agy_st["cli_available"],
                    "timestamp": time.time()
                })

            server.router.add_get("/", ping_handler)
            server.router.add_get("/ping", ping_handler)
            server.router.add_get("/health", ping_handler)

            runner = web.AppRunner(server)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", HEALTH_PORT)
            await site.start()
            logger.info(f"Health server active on http://0.0.0.0:{HEALTH_PORT}")
        except Exception as e:
            logger.warning(f"Could not bind health server on port {HEALTH_PORT}: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        return

    agy_status = agy_bridge.get_status()
    print("=" * 60)
    print("Peak Arena Reel Automation + Antigravity (AGY) Telegram Bridge")
    print(f"Token: {TELEGRAM_BOT_TOKEN[:10]}...{TELEGRAM_BOT_TOKEN[-6:]}")
    print(f"AGY Runtime: {'ONLINE' if agy_status['cli_available'] else 'OFFLINE'}")
    print(f"Gemini API: {'YES' if GEMINI_API_KEY else 'NO (regex fallback)'}")
    print(f"24/7 Health Endpoint: http://0.0.0.0:{HEALTH_PORT}/health")
    print("=" * 60)

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(60)
        .read_timeout(120)
        .write_timeout(180)
        .pool_timeout(60)
        .post_init(on_bot_startup)
        .build()
    )

    # Video Wizard Conversation: video → prompt → images → DONE
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive_video),
            MessageHandler((filters.TEXT & ~filters.COMMAND) & filters.Regex(URL_REGEX), receive_video),
        ],
        states={
            WAITING_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt),
            ],
            COLLECTING_IMAGES: [
                MessageHandler(filters.PHOTO, collect_image),
                MessageHandler(filters.Document.IMAGE, collect_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_image),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("cron_ping", cron_ping_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("new", reset_command))
    app.add_handler(CommandHandler("set_insta", set_insta_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("agy", handle_agy_message))

    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    app.add_handler(conv)

    # Remote AGY agent handles non-video photos and general text messages
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_agy_photo))
    app.add_handler(MessageHandler((filters.TEXT & ~filters.COMMAND) & ~filters.Regex(URL_REGEX), handle_agy_message))

    print("[+] Bot online. Polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
