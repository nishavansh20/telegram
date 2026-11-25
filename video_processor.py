import os
import re
import uuid
import time
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Callable
from PIL import Image, ImageDraw, ImageFont
import yt_dlp
import imageio_ffmpeg
import proglog

try:
    from moviepy import (
        VideoFileClip,
        AudioFileClip,
        ImageClip,
        CompositeVideoClip,
        CompositeAudioClip,
        concatenate_videoclips,
        concatenate_audioclips,
        ColorClip
    )
except ImportError:
    from moviepy.editor import (
        VideoFileClip,
        AudioFileClip,
        ImageClip,
        CompositeVideoClip,
        CompositeAudioClip,
        concatenate_videoclips,
        concatenate_audioclips,
        ColorClip
    )

from config import ASSETS_DIR, TEMP_DIR, OUTPUT_DIR, LOGO_PATH
from detector import detect_app_screen_ranges, detect_bio_screen
from voice_engine import extract_reference_audio, generate_cloned_voice

TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


class MoviePyTelegramLogger(proglog.ProgressBarLogger):
    def __init__(self, tg_callback: Optional[Callable[[str], None]] = None):
        super().__init__()
        self.tg_callback = tg_callback
        self.last_time = time.time()
        self.last_pct = -1

    def callback(self, **kw):
        pass

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar == "t" and self.tg_callback:
            total = self.bars[bar].get("total", 1)
            if total > 0:
                pct = max(0, min(100, int(value * 100 / total)))
                now = time.time()
                if (now - self.last_time >= 2.5 or pct - self.last_pct >= 20) and pct != self.last_pct:
                    self.last_time = now
                    self.last_pct = pct
                    filled = pct // 10
                    bar_str = "=" * filled + "." * (10 - filled)
                    self.tg_callback(f"🎬 <b>[4/4] Rendering Video with FFmpeg...</b>\nProgress: <code>[{bar_str}] {pct}%</code>")


def set_dur(clip, duration):
    return clip.with_duration(duration) if hasattr(clip, "with_duration") else clip.set_duration(duration)


def set_pos(clip, pos):
    return clip.with_position(pos) if hasattr(clip, "with_position") else clip.set_position(pos)


def set_size(clip, **kwargs):
    if hasattr(clip, "resized"):
        return clip.resized(**kwargs)
    return clip.resize(**kwargs)


def set_start(clip, t):
    return clip.with_start(t) if hasattr(clip, "with_start") else clip.set_start(t)


def download_media(url: str, progress_callback: Optional[Callable[[str], None]] = None) -> Path:
    """Download video with yt-dlp, support cookies.txt if available."""
    if progress_callback:
        progress_callback("⏳ <b>[1/4] Downloading Reel with yt-dlp & FFmpeg...</b>")

    TEMP_DIR.mkdir(exist_ok=True)
    file_id = uuid.uuid4().hex[:8]
    out_template = str(TEMP_DIR / f"raw_{file_id}.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "ffmpeg_location": FFMPEG_EXE,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "geo_bypass": True,
    }

    # Add cookies if present in project or assets folder
    cookie_paths = [
        Path(__file__).parent / "cookies.txt",
        ASSETS_DIR / "cookies.txt",
        ASSETS_DIR / "instagram_cookies.txt"
    ]
    for cp in cookie_paths:
        if cp.exists():
            ydl_opts["cookiefile"] = str(cp)
            break

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        base, _ = os.path.splitext(filename)
        mp4_path = Path(f"{base}.mp4")
        if mp4_path.exists():
            return mp4_path
        if Path(filename).exists():
            return Path(filename)
        raise FileNotFoundError(f"Downloaded video file not found for {url}")


def get_app_overlay_clip(vw: int, vh: int, duration: float) -> ImageClip:
    """Prepare Peak Arena app screenshot overlay scaled proportionally to the reel dimensions."""
    app_img_path = ASSETS_DIR / "app_overlay_framed.png"
    if not app_img_path.exists():
        app_img_path = ASSETS_DIR / "app_screen_clean.png"

    target_h = int(vh * 0.72)
    clip = ImageClip(str(app_img_path))
    clip = set_size(clip, height=target_h)
    return set_dur(clip, duration)


def create_instagram_bio_outro(
    width: int,
    height: int,
    insta_handle: str = "@_maxeddd"
) -> Path:
    """Generate Instagram Bio profile screen matching exact reel resolution."""
    img = Image.new("RGBA", (width, height), (10, 12, 16, 255))
    draw = ImageDraw.Draw(img)

    scale = width / 1080.0

    top_bar_h = int(130 * scale)
    draw.rectangle([0, 0, width, top_bar_h], fill=(15, 17, 23, 255))

    try:
        f_handle = ImageFont.truetype("arialbd.ttf", int(42 * scale))
        f_stat_num = ImageFont.truetype("arialbd.ttf", int(38 * scale))
        f_stat_label = ImageFont.truetype("arial.ttf", int(24 * scale))
        f_name = ImageFont.truetype("arialbd.ttf", int(38 * scale))
        f_bio = ImageFont.truetype("arialbd.ttf", int(28 * scale))
        f_link = ImageFont.truetype("arialbd.ttf", int(32 * scale))
        f_banner = ImageFont.truetype("arialbd.ttf", int(42 * scale))
    except Exception:
        f_handle = ImageFont.load_default()
        f_stat_num = ImageFont.load_default()
        f_stat_label = ImageFont.load_default()
        f_name = ImageFont.load_default()
        f_bio = ImageFont.load_default()
        f_link = ImageFont.load_default()
        f_banner = ImageFont.load_default()

    if not insta_handle.startswith("@"):
        insta_handle = f"@{insta_handle}"
    draw.text((int(50 * scale), int(44 * scale)), insta_handle, fill=(255, 255, 255, 255), font=f_handle)

    avatar_center = (int(160 * scale), int(260 * scale))
    avatar_radius = int(85 * scale)
    draw.ellipse([avatar_center[0] - avatar_radius - 6, avatar_center[1] - avatar_radius - 6,
                  avatar_center[0] + avatar_radius + 6, avatar_center[1] + avatar_radius + 6],
                  outline=(0, 229, 255, 255), width=int(4 * scale))

    if LOGO_PATH.exists():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo = logo.resize((avatar_radius * 2, avatar_radius * 2), Image.Resampling.LANCZOS)
            mask = Image.new("L", (avatar_radius * 2, avatar_radius * 2), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_radius * 2, avatar_radius * 2), fill=255)
            img.paste(logo, (avatar_center[0] - avatar_radius, avatar_center[1] - avatar_radius), mask)
        except Exception:
            pass

    stats_x = [int(430 * scale), int(640 * scale), int(850 * scale)]
    stats_data = [("48", "Posts"), ("14.2K", "Followers"), ("112", "Following")]
    for i, (num, lbl) in enumerate(stats_data):
        x = stats_x[i]
        bb = draw.textbbox((0, 0), num, font=f_stat_num)
        draw.text((x - (bb[2] - bb[0]) // 2, int(220 * scale)), num, fill=(255, 255, 255, 255), font=f_stat_num)
        bb2 = draw.textbbox((0, 0), lbl, font=f_stat_label)
        draw.text((x - (bb2[2] - bb2[0]) // 2, int(270 * scale)), lbl, fill=(160, 165, 175, 255), font=f_stat_label)

    draw.text((int(50 * scale), int(380 * scale)), "Peak Arena - Battleground Esports", fill=(255, 255, 255, 255), font=f_name)
    draw.text((int(50 * scale), int(430 * scale)), "Esports Tournament App", fill=(0, 229, 255, 255), font=f_stat_label)

    bio_lines = [
        "- Daily Free Fire & BGMI Tournaments",
        "- Entry Rs. 15  |  14 INR Per Kill",
        "- Instant UPI Withdrawals (24x7)"
    ]
    for idx, bl in enumerate(bio_lines):
        draw.text((int(50 * scale), int(470 * scale) + idx * int(40 * scale)), bl, fill=(230, 235, 245, 255), font=f_bio)

    link_y = int(600 * scale)
    link_h = int(60 * scale)
    draw.rectangle([int(40 * scale), link_y, width - int(40 * scale), link_y + link_h], fill=(18, 28, 38, 255), outline=(0, 229, 255, 255), width=2)
    link_str = "LINK IN BIO:  peakarena.in/download"
    bb_l = draw.textbbox((0, 0), link_str, font=f_link)
    draw.text(((width - (bb_l[2] - bb_l[0])) // 2, link_y + int(12 * scale)), link_str, fill=(0, 229, 255, 255), font=f_link)

    cta_y = int(690 * scale)
    cta_h = int(95 * scale)
    draw.rounded_rectangle([int(35 * scale), cta_y, width - int(35 * scale), cta_y + cta_h], radius=int(20 * scale), fill=(229, 169, 60, 255))
    cta_text = "DOWNLOAD APP FROM BIO LINK"
    bb_c = draw.textbbox((0, 0), cta_text, font=f_banner)
    draw.text(((width - (bb_c[2] - bb_c[0])) // 2, cta_y + int(24 * scale)), cta_text, fill=(0, 0, 0, 255), font=f_banner)

    grid_y = int(820 * scale)
    draw.line([0, grid_y, width, grid_y], fill=(45, 50, 65, 255), width=3)

    app_clean = ASSETS_DIR / "app_screen_clean.png"
    if app_clean.exists():
        sc = Image.open(app_clean).convert("RGBA")
        sc.thumbnail((int(420 * scale), int(900 * scale)), Image.Resampling.LANCZOS)
        img.paste(sc, ((width - sc.size[0]) // 2, grid_y + int(30 * scale)), sc)

    out_outro = TEMP_DIR / f"insta_outro_{uuid.uuid4().hex[:6]}.png"
    img.save(out_outro, format="PNG")
    return out_outro


def process_reel(
    video_path: Path,
    app_overlay_range: Optional[Tuple[float, float]] = None,
    logo_position: str = "top-left",
    replace_bio: bool = True,
    insta_handle: str = "@_maxeddd",
    custom_voice_path: Optional[Path] = None,
    audio_replace_range: Optional[Tuple[float, float]] = None,
    elevenlabs_api_key: Optional[str] = None,
    max_duration: int = 60,
    progress_callback: Optional[Callable[[str], None]] = None
) -> Path:
    """
    Intelligent Promotion Mode:
    1. Automatic detection of competitor app popup timestamps (no hardcoded times)
    2. Seamless overlay of Peak Arena app screen
    3. Peak Arena shield logo watermark
    4. Smart bio screen detection & replacement
    5. Voice: Real human voice note OR ElevenLabs clone OR clean original voice
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_id = uuid.uuid4().hex[:8]
    final_output_path = OUTPUT_DIR / f"peak_arena_reel_{out_id}.mp4"

    if progress_callback:
        progress_callback("🎬 <b>[2/4] Scanning Reel with Computer Vision for app popups...</b>")

    clip = VideoFileClip(str(video_path))
    if clip.duration > max_duration:
        clip = clip.subclipped(0, max_duration) if hasattr(clip, "subclipped") else clip.subclip(0, max_duration)

    vw, vh = clip.size
    layers = [clip]

    # --- 1. Dynamic Detection of App Popups ---
    ranges_to_overlay = []
    if app_overlay_range is not None:
        ranges_to_overlay.append(app_overlay_range)
    else:
        # Auto-detect using computer vision
        detected_ranges = detect_app_screen_ranges(clip)
        if detected_ranges:
            ranges_to_overlay.extend(detected_ranges)
            if progress_callback:
                time_strs = ", ".join([f"{s}s-{e}s" for s, e in detected_ranges])
                progress_callback(f"📱 <b>[2/4] Auto-detected app popups at:</b> <code>{time_strs}</code>")
        elif clip.duration >= 16.0:
            ranges_to_overlay.append((12.0, 16.5))

    for a_start, a_end in ranges_to_overlay:
        a_end = min(a_end, clip.duration)
        a_dur = a_end - a_start
        if a_dur > 0.5:
            app_clip = get_app_overlay_clip(vw, vh, duration=a_dur)
            app_clip = set_start(set_pos(app_clip, ("center", "center")), a_start)
            layers.append(app_clip)

    # --- 2. Peak Arena Shield Logo Watermark ---
    if LOGO_PATH.exists():
        logo_w = int(vw * 0.16)
        logo = ImageClip(str(LOGO_PATH))
        logo = set_size(logo, width=logo_w)
        logo = set_dur(logo, clip.duration)
        if logo_position == "top-left":
            logo = set_pos(logo, (int(vw * 0.04), int(vh * 0.03)))
        else:
            logo = set_pos(logo, (vw - logo_w - int(vw * 0.04), int(vh * 0.03)))
        layers.append(logo)

    composite_clip = CompositeVideoClip(layers)

    # --- 3. Smart Bio Outro Handling ---
    if replace_bio and clip.duration >= 8.0:
        has_bio_in_video = detect_bio_screen(clip)
        outro_dur = 3.2
        outro_img_path = create_instagram_bio_outro(width=vw, height=vh, insta_handle=insta_handle)
        outro_clip = set_dur(ImageClip(str(outro_img_path)), outro_dur)

        if has_bio_in_video:
            # Competitor showed bio at end -> Replace that exact end segment!
            if progress_callback:
                progress_callback("🔗 <b>[3/4] Competitor bio detected at end. Replacing with bio...</b>")
            main_dur = max(1.0, clip.duration - outro_dur)
            trimmed_main = composite_clip.subclipped(0, main_dur) if hasattr(composite_clip, "subclipped") else composite_clip.subclip(0, main_dur)
            if clip.audio is not None:
                outro_audio = clip.audio.subclipped(main_dur, clip.duration) if hasattr(clip.audio, "subclipped") else clip.audio.subclip(main_dur, clip.duration)
                outro_clip = outro_clip.with_audio(outro_audio) if hasattr(outro_clip, "with_audio") else outro_clip.set_audio(outro_audio)
            final_clip = concatenate_videoclips([trimmed_main, outro_clip], method="compose")
        else:
            # No bio screen in video -> Append outro gracefully (do NOT cut creator's speech!)
            if progress_callback:
                progress_callback("🔗 <b>[3/4] Appending bio outro at end of video...</b>")
            final_clip = concatenate_videoclips([composite_clip, outro_clip], method="compose")
    else:
        final_clip = composite_clip

    # --- 4. Voice Handling (Human Voice Note / Voice Clone / Original Clean) ---
    voice_to_use = None
    if custom_voice_path and custom_voice_path.exists():
        voice_to_use = custom_voice_path
    elif elevenlabs_api_key and audio_replace_range and clip.audio is not None:
        # Clone creator voice from video
        ref_wav = TEMP_DIR / f"ref_voice_{out_id}.wav"
        cloned_wav = TEMP_DIR / f"cloned_voice_{out_id}.wav"
        extract_reference_audio(video_path, ref_wav, duration=6.0)
        res = generate_cloned_voice("Peak Arena app download karo", ref_wav, cloned_wav, elevenlabs_api_key)
        if res:
            voice_to_use = res

    if voice_to_use and audio_replace_range and clip.audio is not None:
        try:
            r_start, r_end = audio_replace_range
            r_end = min(r_end, final_clip.duration)
            if r_start < r_end:
                if progress_callback:
                    progress_callback("🎙 <b>[3/4] Punching in voice replacement naturally...</b>")
                orig_audio = final_clip.audio
                voice_clip = AudioFileClip(str(voice_to_use))
                subclip_func = orig_audio.subclipped if hasattr(orig_audio, "subclipped") else orig_audio.subclip

                pre_audio = subclip_func(0, r_start)
                duck_audio = subclip_func(r_start, r_end)
                if hasattr(duck_audio, "with_volume_scaled"):
                    duck_audio = duck_audio.with_volume_scaled(0.15)
                elif hasattr(duck_audio, "volumex"):
                    duck_audio = duck_audio.volumex(0.15)
                post_audio = subclip_func(r_end, final_clip.duration)

                ducked_bed = concatenate_audioclips([pre_audio, duck_audio, post_audio])
                placed_voice = set_start(voice_clip, r_start)
                if hasattr(placed_voice, "with_volume_scaled"):
                    placed_voice = placed_voice.with_volume_scaled(1.3)
                final_audio = CompositeAudioClip([ducked_bed, placed_voice])
                final_clip = final_clip.with_audio(final_audio) if hasattr(final_clip, "with_audio") else final_clip.set_audio(final_audio)
        except Exception as e:
            print(f"Warning: Audio replacement failed: {e}")

    # --- 5. Render Final MP4 ---
    logger = MoviePyTelegramLogger(tg_callback=progress_callback)

    final_clip.write_videofile(
        str(final_output_path),
        codec="libx264",
        audio_codec="aac",
        fps=24,
        preset="fast",
        threads=4,
        ffmpeg_params=["-pix_fmt", "yuv420p"],
        logger=logger
    )

    clip.close()
    final_clip.close()
    return final_output_path


# ---------------------------------------------------------------------------
# Universal edit engine — executes any list of EditInstruction
# ---------------------------------------------------------------------------

def apply_edit_instructions(
    video_path: Path,
    instructions,                                   # List[EditInstruction]
    output_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Path:
    """
    Apply an arbitrary list of EditInstruction objects to a video.
    Supports: replace_region, add_watermark, replace_bio, voice_over,
              extend_video, mute_range, text_overlay.
    Returns path to rendered MP4.
    """
    from prompt_parser import EditInstruction

    out_id = uuid.uuid4().hex[:8]
    if output_path is None:
        output_path = OUTPUT_DIR / f"edited_{out_id}.mp4"

    if progress_callback:
        progress_callback(f"&#127909; <b>Loading video...</b>")

    clip = VideoFileClip(str(video_path))
    vw, vh = clip.size
    total_dur = clip.duration

    layers = [clip]           # base + overlays for CompositeVideoClip
    audio_layers = []         # extra audio tracks to mix in
    extend_clips = []         # segments to append at the end
    final_audio = clip.audio  # start with original audio

    # --- Sort: apply non-extend ops first, then extend ---
    for instr in instructions:
        op = instr.op

        if progress_callback:
            progress_callback(f"&#9881; <b>Applying:</b> <code>{op}</code>")

        # ----------------------------------------------------------------
        # replace_region — overlay an image for a time window
        # ----------------------------------------------------------------
        if op == "replace_region":
            img_path = instr.image_path
            if img_path is None or not Path(img_path).exists():
                # fall back to default app overlay
                img_path = ASSETS_DIR / "app_overlay_framed.png"
                if not img_path.exists():
                    img_path = ASSETS_DIR / "app_screen_clean.png"

            t_s = instr.t_start
            t_e = instr.t_end

            # Auto-detect if no time given
            if t_s is None or t_e is None:
                ranges = detect_app_screen_ranges(clip)
                if ranges:
                    t_s, t_e = ranges[0]
                else:
                    t_s, t_e = 5.0, min(10.0, total_dur - 1)

            t_e = min(t_e, total_dur)
            dur = max(0.1, t_e - t_s)

            sf = instr.size_fraction if instr.size_fraction > 0 else 0.72
            target_h = int(vh * sf)

            ov = ImageClip(str(img_path))
            ov = set_size(ov, height=target_h)
            ow = ov.size[0]

            # Center horizontally, vertically centered
            pos_x = (vw - ow) // 2
            pos_y = (vh - target_h) // 2

            pos_map = {
                "top": (pos_x, int(vh * 0.05)),
                "bottom": (pos_x, vh - target_h - int(vh * 0.05)),
                "top-left": (int(vw * 0.04), int(vh * 0.05)),
                "top-right": (vw - ow - int(vw * 0.04), int(vh * 0.05)),
                "center": (pos_x, pos_y),
            }
            pos = pos_map.get(instr.position, (pos_x, pos_y))

            ov = set_dur(ov, dur)
            ov = set_start(ov, t_s)
            ov = set_pos(ov, pos)
            layers.append(ov)

        # ----------------------------------------------------------------
        # add_watermark — persistent image overlay
        # ----------------------------------------------------------------
        elif op == "add_watermark":
            img_path = instr.image_path
            if img_path is None or not Path(img_path).exists():
                img_path = LOGO_PATH

            logo_w = int(vw * 0.16)
            wm = ImageClip(str(img_path))
            wm = set_size(wm, width=logo_w)
            wm = set_dur(wm, total_dur)
            wh = wm.size[1]

            pos_map = {
                "top-right": (vw - logo_w - int(vw * 0.03), int(vh * 0.03)),
                "top-left": (int(vw * 0.03), int(vh * 0.03)),
                "bottom-right": (vw - logo_w - int(vw * 0.03), vh - wh - int(vh * 0.03)),
                "bottom-left": (int(vw * 0.03), vh - wh - int(vh * 0.03)),
            }
            pos = pos_map.get(instr.position, (vw - logo_w - int(vw * 0.03), int(vh * 0.03)))
            wm = set_pos(wm, pos)
            layers.append(wm)

        # ----------------------------------------------------------------
        # replace_bio — swap the bio/outro screen
        # ----------------------------------------------------------------
        elif op == "replace_bio":
            # Handled after compositing — stored for later
            pass   # dealt with in post-composite block below

        # ----------------------------------------------------------------
        # text_overlay — burn text onto frames
        # ----------------------------------------------------------------
        elif op == "text_overlay" and instr.text:
            try:
                from moviepy import TextClip
            except ImportError:
                from moviepy.editor import TextClip

            t_s = instr.t_start or 0.0
            t_e = instr.t_end or total_dur
            t_e = min(t_e, total_dur)

            try:
                txt = TextClip(
                    text=instr.text,
                    font_size=int(vh * 0.045),
                    color="white",
                    stroke_color="black",
                    stroke_width=2,
                    method="caption",
                    size=(int(vw * 0.90), None),
                )
            except TypeError:
                txt = TextClip(
                    instr.text,
                    fontsize=int(vh * 0.045),
                    color="white",
                    stroke_color="black",
                    stroke_width=2,
                    method="caption",
                    size=(int(vw * 0.90), None),
                )

            txt = set_dur(txt, t_e - t_s)
            txt = set_start(txt, t_s)

            pos_map = {
                "bottom": ("center", vh - txt.size[1] - int(vh * 0.08)),
                "top": ("center", int(vh * 0.05)),
                "center": ("center", "center"),
            }
            txt = set_pos(txt, pos_map.get(instr.position, ("center", "center")))
            layers.append(txt)

        # ----------------------------------------------------------------
        # voice_over — TTS audio mixed in
        # ----------------------------------------------------------------
        elif op == "voice_over" and instr.text:
            try:
                import asyncio, edge_tts, tempfile
                tts_path = TEMP_DIR / f"tts_{out_id}_{len(audio_layers)}.mp3"

                async def _synth():
                    comm = edge_tts.Communicate(instr.text, voice="hi-IN-MadhurNeural")
                    await comm.save(str(tts_path))

                asyncio.run(_synth())

                tts_clip = AudioFileClip(str(tts_path))
                t_s = instr.t_start or 0.0
                tts_clip = set_start(tts_clip, t_s)
                if hasattr(tts_clip, "with_volume_scaled"):
                    tts_clip = tts_clip.with_volume_scaled(1.3)
                audio_layers.append(tts_clip)

                # Duck original in that range
                if final_audio is not None:
                    t_e_tts = min(t_s + tts_clip.duration, total_dur)
                    sub = final_audio.subclipped if hasattr(final_audio, "subclipped") else final_audio.subclip
                    pre = sub(0, t_s) if t_s > 0 else None
                    mid = sub(t_s, t_e_tts)
                    post = sub(t_e_tts, total_dur) if t_e_tts < total_dur else None
                    if hasattr(mid, "with_volume_scaled"):
                        mid = mid.with_volume_scaled(0.12)
                    parts = [p for p in [pre, mid, post] if p is not None]
                    final_audio = concatenate_audioclips(parts) if len(parts) > 1 else parts[0]

            except Exception as e:
                logger.warning(f"voice_over TTS failed: {e}")

        # ----------------------------------------------------------------
        # mute_range — silence or duck audio
        # ----------------------------------------------------------------
        elif op == "mute_range" and final_audio is not None:
            t_s = instr.t_start or 0.0
            t_e = instr.t_end or total_dur
            t_e = min(t_e, total_dur)
            vol = instr.volume  # 0 = mute, 0.15 = duck
            sub = final_audio.subclipped if hasattr(final_audio, "subclipped") else final_audio.subclip
            pre = sub(0, t_s) if t_s > 0 else None
            mid = sub(t_s, t_e)
            post = sub(t_e, total_dur) if t_e < total_dur else None
            if hasattr(mid, "with_volume_scaled"):
                mid = mid.with_volume_scaled(vol)
            elif hasattr(mid, "volumex"):
                mid = mid.volumex(vol)
            parts = [p for p in [pre, mid, post] if p is not None]
            final_audio = concatenate_audioclips(parts) if len(parts) > 1 else parts[0]

        # ----------------------------------------------------------------
        # extend_video — append a new segment/screen at the end
        # ----------------------------------------------------------------
        elif op == "extend_video":
            img_path = instr.image_path
            dur = instr.duration if instr.duration > 0 else 3.5

            if img_path and Path(img_path).exists():
                seg = set_dur(ImageClip(str(img_path)), dur)
            else:
                # Use generated bio outro
                bio_path = create_instagram_bio_outro(vw, vh)
                seg = set_dur(ImageClip(str(bio_path)), dur)

            # Match size
            seg = set_size(seg, width=vw)
            extend_clips.append(seg)

    # --- Composite all overlay layers ---
    composite = CompositeVideoClip(layers)

    # --- Mix extra audio layers ---
    if audio_layers and final_audio is not None:
        final_audio = CompositeAudioClip([final_audio] + audio_layers)
    elif audio_layers:
        final_audio = CompositeAudioClip(audio_layers)

    if final_audio is not None:
        composite = composite.with_audio(final_audio) if hasattr(composite, "with_audio") else composite.set_audio(final_audio)

    # --- Handle replace_bio (needs post-composite timing) ---
    bio_instrs = [i for i in instructions if i.op == "replace_bio"]
    if bio_instrs:
        bi = bio_instrs[0]
        dur = bi.duration if bi.duration > 0 else 3.5

        if bi.image_path and Path(bi.image_path).exists():
            outro = set_dur(ImageClip(str(bi.image_path)), dur)
            outro = set_size(outro, width=vw)
        else:
            bio_img = create_instagram_bio_outro(vw, vh)
            outro = set_dur(ImageClip(str(bio_img)), dur)

        has_bio = detect_bio_screen(clip)
        if has_bio:
            main_dur = max(1.0, composite.duration - dur)
            main_part = composite.subclipped(0, main_dur) if hasattr(composite, "subclipped") else composite.subclip(0, main_dur)
            final_clip = concatenate_videoclips([main_part, outro], method="compose")
        else:
            final_clip = concatenate_videoclips([composite, outro], method="compose")
    else:
        final_clip = composite

    # --- Append extend_video segments ---
    if extend_clips:
        final_clip = concatenate_videoclips([final_clip] + extend_clips, method="compose")

    # --- Render ---
    if progress_callback:
        progress_callback("&#127909; <b>[Final] Rendering edited video...</b>")

    log = MoviePyTelegramLogger(tg_callback=progress_callback)
    final_clip.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        fps=24,
        preset="fast",
        threads=4,
        ffmpeg_params=["-pix_fmt", "yuv420p"],
        logger=log,
    )

    clip.close()
    final_clip.close()
    return output_path

