import os
import gc
import re
import uuid
import time
import logging
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

from config import ASSETS_DIR, TEMP_DIR, OUTPUT_DIR, LOGO_PATH, LOW_MEMORY_MODE
from detector import probe_video_info, detect_app_screen_ranges, detect_bio_screen
from voice_engine import extract_reference_audio, generate_cloned_voice

TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


def _load_font(bold: bool, size: int):
    """Load bold/regular sans-serif font on Windows or Linux Docker."""
    candidates = (
        ["arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


class MoviePyTelegramLogger(proglog.ProgressBarLogger):
    def __init__(self, tg_callback: Optional[Callable[[str], None]] = None):
        super().__init__()
        self.tg_callback = tg_callback
        self.last_time = time.time()
        self.last_pct = -1

    def callback(self, **kw):
        pass

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar in ("frame_index", "t") and self.tg_callback:
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


ASSET_ALIASES = {
    "logo": "logo.png",
    "logo.png": "logo.png",
    "watermark": "logo.png",
    "app": "app_overlay_framed.png",
    "overlay": "app_overlay_framed.png",
    "app_overlay": "app_overlay_framed.png",
    "app_overlay_framed.png": "app_overlay_framed.png",
    "clean": "app_screen_clean.png",
    "app_clean": "app_screen_clean.png",
    "app_screen_clean.png": "app_screen_clean.png",
    "bio": "insta_bio_outro.png",
    "outro": "insta_bio_outro.png",
    "insta_bio_outro.png": "insta_bio_outro.png",
}


def update_default_asset(source_image_path: str, target_asset: str) -> Dict[str, str]:
    """Replace one of the default Peak Arena images in assets/ cleanly."""
    key = target_asset.strip().lower()
    custom_flag = ASSETS_DIR / ".custom_bio"
    if key == "reset_bio":
        if custom_flag.exists():
            custom_flag.unlink()
        return {"status": "reset", "asset": "auto-generated bio outro"}

    canonical = ASSET_ALIASES.get(key)
    if not canonical:
        return {
            "error": f"Unknown target_asset '{target_asset}'. Valid: logo.png, app_overlay_framed.png, app_screen_clean.png, insta_bio_outro.png, reset_bio"
        }

    src = Path(source_image_path)
    if not src.exists():
        return {"error": f"Source image not found: {source_image_path}"}

    ASSETS_DIR.mkdir(exist_ok=True)
    dest = ASSETS_DIR / canonical
    with Image.open(src) as im:
        im.convert("RGBA").save(dest, format="PNG")

    if canonical == "insta_bio_outro.png":
        custom_flag.write_text("1", encoding="utf-8")

    return {"status": "updated", "asset": canonical, "path": str(dest)}


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

    f_handle = _load_font(True, int(42 * scale))
    f_stat_num = _load_font(True, int(38 * scale))
    f_stat_label = _load_font(False, int(24 * scale))
    f_name = _load_font(True, int(38 * scale))
    f_bio = _load_font(True, int(28 * scale))
    f_link = _load_font(True, int(32 * scale))
    f_banner = _load_font(True, int(42 * scale))

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


def _resolve_bio_outro_image(width: int, height: int, insta_handle: str) -> Path:
    """Use user-replaced custom bio image if flagged, else generate Peak Arena bio card."""
    custom_flag = ASSETS_DIR / ".custom_bio"
    custom_bio = ASSETS_DIR / "insta_bio_outro.png"
    if custom_flag.exists() and custom_bio.exists():
        img = Image.open(custom_bio).convert("RGBA")
        bg = Image.new("RGBA", (width, height), (10, 12, 16, 255))
        img.thumbnail((width, height), Image.Resampling.LANCZOS)
        bg.paste(img, ((width - img.width) // 2, (height - img.height) // 2), img)
        out_path = TEMP_DIR / f"custom_outro_{uuid.uuid4().hex[:6]}.png"
        bg.save(out_path, format="PNG")
        return out_path
    return create_instagram_bio_outro(width=width, height=height, insta_handle=insta_handle)


def _run_ffmpeg_with_progress(
    cmd: List[str],
    expected_duration: float,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> None:
    """Execute ffmpeg command and stream [4/4] progress updates cleanly."""
    if progress_callback:
        progress_callback("🎬 <b>[4/4] Rendering Video with FFmpeg...</b>\nProgress: <code>[..........] 0%</code>")

    full_cmd = [cmd[0], "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *cmd[1:]]
    proc = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    last_time = time.time()
    last_pct = 0
    if proc.stdout is not None:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms=") and progress_callback and expected_duration > 0:
                try:
                    out_sec = int(line.split("=", 1)[1]) / 1_000_000.0
                    pct = max(0, min(99, int(out_sec * 100 / expected_duration)))
                    now = time.time()
                    if (now - last_time >= 2.5 or pct - last_pct >= 20) and pct != last_pct:
                        last_time = now
                        last_pct = pct
                        filled = pct // 10
                        bar_str = "=" * filled + "." * (10 - filled)
                        progress_callback(f"🎬 <b>[4/4] Rendering Video with FFmpeg...</b>\nProgress: <code>[{bar_str}] {pct}%</code>")
                except ValueError:
                    pass
    _, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed (code {proc.returncode}): {(stderr or '').strip()[:600]}")


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
    Intelligent Promotion Mode (Single-pass low-RAM FFmpeg pipeline):
    1. Fast FFmpeg-piped CV scan for competitor app popup timestamps
    2. Seamless overlay of Peak Arena app screen
    3. Peak Arena shield logo watermark
    4. Smart bio screen detection & replacement
    5. Voice: Real human voice note OR ElevenLabs clone OR clean original voice
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    out_id = uuid.uuid4().hex[:8]
    final_output_path = OUTPUT_DIR / f"peak_arena_reel_{out_id}.mp4"
    temp_artifacts: List[Path] = []

    try:
        if progress_callback:
            progress_callback("🎬 <b>[2/4] Scanning Reel with Computer Vision for app popups...</b>")

        orig_dur, orig_w, orig_h, has_audio = probe_video_info(video_path)
        clip_dur = min(orig_dur, float(max_duration)) if orig_dur > 0 else float(max_duration)

        if LOW_MEMORY_MODE and orig_w > 720:
            out_w = 720
            out_h = max(2, int(round(orig_h * (720.0 / orig_w))) // 2 * 2)
        else:
            out_w = max(2, (orig_w // 2) * 2)
            out_h = max(2, (orig_h // 2) * 2)

        # --- 1. Dynamic Detection of App Popups ---
        ranges_to_overlay: List[Tuple[float, float]] = []
        if app_overlay_range is not None:
            ranges_to_overlay.append(app_overlay_range)
        else:
            detected_ranges = detect_app_screen_ranges(video_path, max_duration=clip_dur)
            if detected_ranges:
                ranges_to_overlay.extend(detected_ranges)
                if progress_callback:
                    time_strs = ", ".join(f"{s}s-{e}s" for s, e in detected_ranges)
                    progress_callback(f"📱 <b>[2/4] Auto-detected app popups at:</b> <code>{time_strs}</code>")
            elif clip_dur >= 16.0:
                ranges_to_overlay.append((12.0, 16.5))

        # --- 2. Bio Outro Detection ---
        outro_dur = 3.2
        use_bio = bool(replace_bio and clip_dur >= 8.0)
        has_bio_in_video = False
        outro_img_path: Optional[Path] = None

        if use_bio:
            has_bio_in_video = detect_bio_screen(video_path, max_duration=clip_dur)
            outro_img_path = _resolve_bio_outro_image(out_w, out_h, insta_handle=insta_handle)
            temp_artifacts.append(outro_img_path)
            if progress_callback:
                if has_bio_in_video:
                    progress_callback("🔗 <b>[3/4] Competitor bio detected at end. Replacing with bio...</b>")
                else:
                    progress_callback("🔗 <b>[3/4] Appending bio outro at end of video...</b>")

        # --- 3. Optional Voice Replacement ---
        voice_to_use: Optional[Path] = None
        if custom_voice_path and custom_voice_path.exists():
            voice_to_use = custom_voice_path
        elif elevenlabs_api_key and audio_replace_range and has_audio:
            ref_wav = TEMP_DIR / f"ref_voice_{out_id}.wav"
            cloned_wav = TEMP_DIR / f"cloned_voice_{out_id}.wav"
            extract_reference_audio(video_path, ref_wav, duration=6.0)
            temp_artifacts.append(ref_wav)
            res = generate_cloned_voice("Peak Arena app download karo", ref_wav, cloned_wav, elevenlabs_api_key)
            if res:
                voice_to_use = res
                temp_artifacts.append(cloned_wav)

        # --- 4. Build Single-Pass FFmpeg Graph ---
        main_dur = max(1.0, clip_dur - outro_dur) if (use_bio and has_bio_in_video) else clip_dur
        total_out_dur = (main_dur + outro_dur) if use_bio else clip_dur

        inputs: List[str] = ["-i", str(video_path)]
        filter_parts: List[str] = [
            f"[0:v]trim=0:{main_dur:.3f},setpts=PTS-STARTPTS,fps=24,scale={out_w}:{out_h}:flags=fast_bilinear,setsar=1[v0]"
        ]
        v_cur = "v0"

        app_img_path = ASSETS_DIR / "app_overlay_framed.png"
        if not app_img_path.exists():
            app_img_path = ASSETS_DIR / "app_screen_clean.png"
        valid_ranges = [
            (max(0.0, s), min(e, main_dur))
            for s, e in ranges_to_overlay
            if min(e, main_dur) - max(0.0, s) > 0.5
        ]
        if valid_ranges and app_img_path.exists():
            app_idx = len(inputs) // 2
            inputs.extend(["-i", str(app_img_path)])
            target_app_h = int(out_h * 0.72)
            enable_expr = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e in valid_ranges)
            filter_parts.append(f"[{app_idx}:v]scale=-1:{target_app_h}[app_ov]")
            filter_parts.append(f"[{v_cur}][app_ov]overlay=(W-w)/2:(H-h)/2:enable='{enable_expr}'[v_app]")
            v_cur = "v_app"

        logo_file = ASSETS_DIR / "logo.png"
        if not logo_file.exists():
            logo_file = LOGO_PATH
        if logo_file.exists():
            logo_idx = len(inputs) // 2
            inputs.extend(["-i", str(logo_file)])
            logo_w = max(20, int(out_w * 0.16))
            pad_x = int(out_w * 0.04)
            pad_y = int(out_h * 0.03)
            lx = str(pad_x) if logo_position == "top-left" else f"W-w-{pad_x}"
            filter_parts.append(f"[{logo_idx}:v]scale={logo_w}:-1[wm]")
            filter_parts.append(f"[{v_cur}][wm]overlay={lx}:{pad_y}[v_wm]")
            v_cur = "v_wm"

        if use_bio and outro_img_path is not None:
            outro_idx = len(inputs) // 2
            inputs.extend(["-loop", "1", "-t", f"{outro_dur:.2f}", "-framerate", "24", "-i", str(outro_img_path)])
            filter_parts.append(f"[{outro_idx}:v]scale={out_w}:{out_h},setsar=1,format=yuv420p[v_outro]")
            filter_parts.append(f"[{v_cur}][v_outro]concat=n=2:v=1:a=0[vout]")
            v_cur = "vout"
        else:
            filter_parts.append(f"[{v_cur}]format=yuv420p[vout]")
            v_cur = "vout"

        map_audio: List[str] = []
        if has_audio:
            audio_trim_end = clip_dur if (use_bio and has_bio_in_video) else main_dur
            filter_parts.append(f"[0:a]atrim=0:{audio_trim_end:.3f},asetpts=PTS-STARTPTS[a_base]")
            a_cur = "a_base"

            if use_bio and not has_bio_in_video:
                filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=44100:d={outro_dur:.2f}[a_sil]")
                filter_parts.append(f"[{a_cur}][a_sil]concat=n=2:v=0:a=1[a_ext]")
                a_cur = "a_ext"

            if voice_to_use and audio_replace_range:
                r_start, r_end = audio_replace_range
                r_end = min(r_end, total_out_dur)
                if r_start < r_end:
                    if progress_callback:
                        progress_callback("🎙 <b>[3/4] Punching in voice replacement naturally...</b>")
                    v_idx = len(inputs) // 2
                    inputs.extend(["-i", str(voice_to_use)])
                    delay_ms = int(max(0.0, r_start) * 1000)
                    filter_parts.append(
                        f"[{a_cur}]volume=enable='between(t,{r_start:.2f},{r_end:.2f})':volume=0.15[a_duck]"
                    )
                    filter_parts.append(
                        f"[{v_idx}:a]adelay={delay_ms}|{delay_ms},volume=1.3[a_punched]"
                    )
                    filter_parts.append("[a_duck][a_punched]amix=inputs=2:duration=first:dropout_transition=0[aout]")
                    a_cur = "aout"

            map_audio = ["-map", f"[{a_cur}]", "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]

        threads = "1" if LOW_MEMORY_MODE else "2"
        preset = "ultrafast" if LOW_MEMORY_MODE else "veryfast"

        cmd = [
            FFMPEG_EXE, "-y",
            *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", f"[{v_cur}]",
            *map_audio,
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", "24",
            "-threads", threads,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(final_output_path),
        ]

        _run_ffmpeg_with_progress(cmd, expected_duration=total_out_dur, progress_callback=progress_callback)
        return final_output_path
    finally:
        for artifact in temp_artifacts:
            try:
                if artifact.exists():
                    artifact.unlink()
            except Exception:
                pass
        gc.collect()


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
    if LOW_MEMORY_MODE and clip.size[0] > 720:
        ow, oh = clip.size
        even_h = max(2, int(round(oh * (720.0 / ow))) // 2 * 2)
        clip = clip.resized((720, even_h)) if hasattr(clip, "resized") else clip.resize((720, even_h))
    vw, vh = clip.size
    total_dur = clip.duration

    layers = [clip]           # base + overlays for CompositeVideoClip
    audio_layers = []         # extra audio tracks to mix in
    extend_clips = []         # segments to append at the end
    final_audio = clip.audio  # start with original audio
    final_clip = None

    try:
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
                    ranges = detect_app_screen_ranges(video_path)
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
                    img_path = ASSETS_DIR / "logo.png" if (ASSETS_DIR / "logo.png").exists() else LOGO_PATH

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
                    import asyncio, edge_tts
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
                vol = instr.volume
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
                    bio_path = _resolve_bio_outro_image(vw, vh, "@_maxeddd")
                    seg = set_dur(ImageClip(str(bio_path)), dur)

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
                bio_img = _resolve_bio_outro_image(vw, vh, "@_maxeddd")
                outro = set_dur(ImageClip(str(bio_img)), dur)

            has_bio = detect_bio_screen(video_path)
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
            progress_callback("🎬 <b>[Final] Rendering edited video...</b>")

        log = MoviePyTelegramLogger(tg_callback=progress_callback)
        final_clip.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            fps=24,
            preset="ultrafast" if LOW_MEMORY_MODE else "veryfast",
            threads=1 if LOW_MEMORY_MODE else 2,
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
            logger=log,
        )
        return output_path
    finally:
        try:
            clip.close()
        except Exception:
            pass
        if final_clip is not None and final_clip is not clip:
            try:
                final_clip.close()
            except Exception:
                pass
        gc.collect()

