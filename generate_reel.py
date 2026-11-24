import os
import sys
import random
import subprocess
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import imageio_ffmpeg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
CLIPS_DIR = os.path.join(ASSETS_DIR, "clips")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

# 6 Rotating Viral Themes for Daily Generation
VIRAL_THEMES = [
    {
        "badge": "• DAILY REAL CASH MATCHES •",
        "badge_color": (220, 38, 38), # Red badge
        "headline": "RS. 15 ENTRY • RS. 14 PER KILL ?",
        "headline_color": (255, 225, 0), # Neon Yellow
        "upi_proof": "UPI Instant: Rs. 420 Received From Peak Arena",
        "cta_code": "PEAK10",
        "hashtags": "#FreeFireIndia #FreeFireEsports #PeakArena #FreeFireTips #GamingIndia #FreeFireMax"
    },
    {
        "badge": "• BEST ESPORTS TOURNAMENT APP •",
        "badge_color": (16, 185, 129), # Emerald Green
        "headline": "DAILY RS. 500+ EARNING APP !",
        "headline_color": (0, 240, 255), # Neon Cyan
        "upi_proof": "GPay: Rs. 650 Received From Peak Arena",
        "cta_code": "WIN500",
        "hashtags": "#FreeFireEarning #EarnMoneyGaming #PeakArenaApp #MobileEsports #FreeFireTournament"
    },
    {
        "badge": "• 100% VERIFIED ANTI-CHEAT •",
        "badge_color": (147, 51, 234), # Purple
        "headline": "NO HACKERS • 100% FAIR ROOMS",
        "headline_color": (255, 184, 0), # Gold
        "upi_proof": "PhonePe: Rs. 920 Received From Peak Arena",
        "cta_code": "FAIRPLAY",
        "hashtags": "#FreeFireHackerFree #PeakArena #FairGaming #EsportsIndia #FreeFireClutch"
    },
    {
        "badge": "• SOLO • DUO • SQUAD ROOMS •",
        "badge_color": (239, 68, 68), # Crimson
        "headline": "TOP 5 SURVIVORS GET PAID !",
        "headline_color": (255, 225, 0), # Yellow
        "upi_proof": "Paytm UPI: Rs. 350 Received From Peak Arena",
        "cta_code": "SQUAD10",
        "hashtags": "#FreeFireSquad #PeakArenaEsports #FreeFireGameplay #FreeFireShorts #GamingCommunity"
    },
    {
        "badge": "• FREE BONUS ON SIGNUP •",
        "badge_color": (14, 165, 233), # Sky Blue
        "headline": "JOIN TOURNAMENT FOR JUST RS. 10",
        "headline_color": (74, 222, 128), # Light Green
        "upi_proof": "UPI: Rs. 500 Transferred To Bank Account",
        "cta_code": "FREE10",
        "hashtags": "#FreeFireBonus #PeakArena #GamingCash #PlayAndEarn #FreeFireReels"
    }
]

def get_font(font_name, size):
    font_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", font_name)
    if os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def draw_outlined_text(draw, pos, text, font, fill_color, stroke_color=(0, 0, 0), stroke_w=5, anchor="mm"):
    x, y = pos
    draw.text((x, y), text, font=font, fill=fill_color, stroke_width=stroke_w, stroke_fill=stroke_color, anchor=anchor)

def detect_active_gameplay_bounds(clip_path, ffmpeg_exe):
    """
    Extracts a frame and detects active non-black rows to eliminate letterboxing.
    Returns (crop_x, crop_y, crop_w, crop_h, orig_w, orig_h)
    """
    temp_frame = os.path.join(OUTPUT_DIR, "_probe_frame.png")
    cmd = [
        ffmpeg_exe, "-y",
        "-ss", "00:00:03",
        "-i", clip_path,
        "-vframes", "1",
        temp_frame
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(temp_frame):
            img = Image.open(temp_frame).convert("RGB")
            arr = np.array(img)
            os.remove(temp_frame)

            orig_h, orig_w, _ = arr.shape
            row_brightness = arr.mean(axis=(1, 2))
            non_black = np.where(row_brightness > 12)[0]
            if len(non_black) > 0:
                min_y = max(0, int(non_black[0]))
                max_y = min(orig_h, int(non_black[-1]))
                # If letterboxing detected (more than 10% black bars)
                if (max_y - min_y) < (orig_h * 0.90):
                    return (0, min_y, orig_w, max_y - min_y, orig_w, orig_h)
            return (0, 0, orig_w, orig_h, orig_w, orig_h)
    except Exception as e:
        print("Probe notice:", e)
    return (0, 0, 1080, 1920, 1080, 1920)

def create_esports_overlay(theme, target_w=1080, target_h=1920, top_h=292, bot_h=293):
    """
    Generates transparent PNG overlay:
    - Top header zone: 0 to top_h (Hook headline, Badge, Instant UPI payment proof)
    - Middle: 100% TRANSPARENT for unobstructed gameplay
    - Bottom footer zone: (target_h - bot_h) to target_h (Peak Arena Logo, CTA, Trust badges)
    """
    img = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_impact_huge = get_font("impact.ttf", 56)
    font_impact_big = get_font("impact.ttf", 40)
    font_bold = get_font("segoeuib.ttf", 30)
    font_pill = get_font("segoeuib.ttf", 24)
    font_small = get_font("segoeuib.ttf", 20)

    # ---------------- 1. TOP HEADER ----------------
    for y in range(top_h):
        draw.line([(0, y), (target_w, y)], fill=(11, 14, 20, 255))
    # Glowing border accent lines at header boundary
    draw.line([(0, top_h - 3), (target_w, top_h - 3)], fill=(255, 184, 0, 255), width=2)
    draw.line([(0, top_h - 1), (target_w, top_h - 1)], fill=(0, 240, 255, 180), width=2)

    # Top Category Badge Pill
    pill_w = 440
    pill_h = 42
    draw.rounded_rectangle(
        [target_w // 2 - pill_w // 2, 26, target_w // 2 + pill_w // 2, 26 + pill_h],
        radius=21,
        fill=theme["badge_color"],
        outline=(255, 255, 255),
        width=2
    )
    draw.text((target_w // 2, 26 + pill_h // 2), theme["badge"], font=font_pill, fill=(255, 255, 255), anchor="mm")

    # Big Main Hook Headline (Impact with bold outline)
    draw_outlined_text(draw, (target_w // 2, 125), theme["headline"], font_impact_huge, theme["headline_color"], stroke_w=6)

    # UPI Instant Payment Proof Notification Card
    notif_w = 660
    notif_h = 56
    notif_y = 195
    draw.rounded_rectangle(
        [target_w // 2 - notif_w // 2, notif_y, target_w // 2 + notif_w // 2, notif_y + notif_h],
        radius=16,
        fill=(18, 26, 42, 255),
        outline=(34, 197, 94),
        width=2
    )
    # Green status dot
    draw.ellipse([target_w // 2 - notif_w // 2 + 22, notif_y + 19, target_w // 2 - notif_w // 2 + 40, notif_y + 37], fill=(34, 197, 94))
    draw.text((target_w // 2 + 15, notif_y + notif_h // 2), theme["upi_proof"], font=font_pill, fill=(74, 222, 128), anchor="mm")

    # ---------------- 2. BOTTOM FOOTER ----------------
    bot_y_start = target_h - bot_h
    for y in range(bot_y_start, target_h):
        draw.line([(0, y), (target_w, y)], fill=(11, 14, 20, 255))
    # Glowing border accent lines at footer boundary
    draw.line([(0, bot_y_start), (target_w, bot_y_start)], fill=(0, 240, 255, 255), width=2)
    draw.line([(0, bot_y_start + 2), (target_w, bot_y_start + 2)], fill=(255, 184, 0, 180), width=2)

    # Peak Arena HD Round Logo
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((90, 90), Image.Resampling.LANCZOS)
            mask = Image.new("L", logo.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, logo.size[0], logo.size[1]), fill=255)
            logo.putalpha(mask)
            img.paste(logo, (70, bot_y_start + 22), logo)
            draw.ellipse([68, bot_y_start + 20, 68 + logo.size[0] + 4, bot_y_start + 20 + logo.size[1] + 4], outline=(255, 184, 0), width=2)
        except Exception as e:
            print("Logo notice:", e)

    draw.text((185, bot_y_start + 48), "PEAK ARENA ESPORTS", font=font_impact_big, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0), anchor="lm")
    draw.text((185, bot_y_start + 88), "India's #1 Real Cash Free Fire & BGMI Platform", font=font_small, fill=(200, 215, 235), anchor="lm")

    # Action CTA Button (Bright Cyan / White outline)
    cta_y = bot_y_start + 128
    cta_h = 76
    cta_w = 960
    draw.rounded_rectangle(
        [target_w // 2 - cta_w // 2, cta_y, target_w // 2 + cta_w // 2, cta_y + cta_h],
        radius=20,
        fill=(0, 240, 255),
        outline=(255, 255, 255),
        width=3
    )
    cta_label = f"DOWNLOAD FROM LINK IN BIO | CODE: {theme['cta_code']}"
    draw.text((target_w // 2, cta_y + cta_h // 2), cta_label, font=font_bold, fill=(10, 15, 25), anchor="mm")

    # Trust Badges Bar
    draw.text((target_w // 2, bot_y_start + 248), "INSTANT 5-MIN UPI CASHOUT  •  100% ANTI-CHEAT  •  50,000+ ACTIVE PLAYERS", font=font_small, fill=(160, 175, 195), anchor="mm")

    overlay_path = os.path.join(OUTPUT_DIR, "temp_esports_overlay.png")
    img.save(overlay_path, "PNG")
    return overlay_path

def generate_daily_reel():
    print("=" * 65)
    print("PEAK ARENA VIRAL REEL AUTOMATION ENGINE (PRO ESPORTS EDITION)")
    print("=" * 65)

    clips = [os.path.join(CLIPS_DIR, f) for f in os.listdir(CLIPS_DIR) if f.lower().endswith(('.mp4', '.mov', '.mkv'))]
    if not clips:
        print(f"Error: No video clips found in '{CLIPS_DIR}'. Drop .mp4 clips there.")
        return

    clip_path = random.choice(clips)
    theme = random.choice(VIRAL_THEMES)
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    print(f"[*] Input Clip: {os.path.basename(clip_path)}")
    print(f"[*] Theme Selected: {theme['headline']}")
    print(f"[*] Promo Code: {theme['cta_code']}")

    # 1. Detect Letterboxing & Aspect Ratio
    crop_x, crop_y, crop_w, crop_h, orig_w, orig_h = detect_active_gameplay_bounds(clip_path, ffmpeg_exe)
    print(f"[*] Active Gameplay Bounds: w={crop_w}, h={crop_h} (Cropped Y: {crop_y} to {crop_y+crop_h})")

    # Target: 1080x1920
    # Header: top 292px, Footer: bottom 293px, Gameplay space: 1335px
    top_h = 292
    bot_h = 293
    game_target_h = 1920 - top_h - bot_h # 1335px

    # Calculate scaling to fit width 1080
    scaled_h = int(crop_h * (1080 / crop_w))
    pad_y = top_h
    if scaled_h > game_target_h:
        # If gameplay is taller than 1335, crop slightly from top/bottom of gameplay
        filter_str = (
            f"[0:v]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
            f"scale=1080:{scaled_h}:flags=lanczos,"
            f"crop=1080:{game_target_h}:0:{(scaled_h - game_target_h)//2},"
            f"pad=1080:1920:0:{pad_y}:color=#0b0e14[bg];"
            f"[bg][1:v]overlay=0:0[v]"
        )
    else:
        # Fits inside gameplay area, center vertically between header & footer
        extra_pad = (game_target_h - scaled_h) // 2
        actual_pad_y = top_h + extra_pad
        filter_str = (
            f"[0:v]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
            f"scale=1080:{scaled_h}:flags=lanczos,"
            f"pad=1080:1920:0:{actual_pad_y}:color=#0b0e14[bg];"
            f"[bg][1:v]overlay=0:0[v]"
        )

    # 2. Render Overlay PNG
    overlay_path = create_esports_overlay(theme, 1080, 1920, top_h, bot_h)

    # 3. Render Final Video
    today_str = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    output_video = os.path.join(OUTPUT_DIR, f"PeakArena_Esports_Reel_{today_str}.mp4")

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", clip_path,
        "-i", overlay_path,
        "-filter_complex", filter_str,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_video
    ]

    print("[*] Encoding 1080x1920 60/30fps Reel with FFmpeg...")
    subprocess.run(cmd, check=True)

    if os.path.exists(overlay_path):
        os.remove(overlay_path)

    print("\n" + "=" * 65)
    print(f"RENDER COMPLETE: {output_video}")
    print(f"File Size: {os.path.getsize(output_video) / (1024 * 1024):.2f} MB")
    print("=" * 65)
    print("\nREADY-TO-POST SOCIAL POST METADATA:")
    print("-" * 65)
    print(f"TITLE: {theme['headline']} | Peak Arena Esports")
    print(f"CAPTION:\n{theme['headline']}!\n{theme['badge']}\n\n"
          f"Use promo code: {theme['cta_code']} to get free ₹10 bonus cash on signup!\n"
          f"Instant 5-Minute UPI Withdrawals.\n"
          f"Download Link in Bio!\n\n"
          f"{theme['hashtags']}")
    print("-" * 65)

if __name__ == "__main__":
    generate_daily_reel()
