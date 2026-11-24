import os
import sys
import argparse
import subprocess
import shutil
import imageio_ffmpeg
import asyncio
import edge_tts

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
REF_DIR = os.path.join(ASSETS_DIR, "references")
APP_SCREEN = os.path.join(ASSETS_DIR, "peak_arena_app_screen.png")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(REF_DIR, exist_ok=True)

ffmpeg_exe = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
ffmpeg_dir = os.path.dirname(ffmpeg_exe) if ffmpeg_exe else ""

def download_video(url):
    print(f"[*] Downloading reference video from: {url}")
    out_tmpl = os.path.join(REF_DIR, "downloaded_reel.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ffmpeg-location", ffmpeg_dir,
        "-o", out_tmpl,
        "--force-overwrites",
        url
    ]
    subprocess.run(cmd, check=True)
    for ext in [".mp4", ".mkv", ".webm", ".mov"]:
        p = os.path.join(REF_DIR, f"downloaded_reel{ext}")
        if os.path.exists(p):
            return p
    return None

def hijack_video(video_path, output_name="PeakArena_Hijacked_Reel.mp4"):
    output_path = os.path.join(OUTPUT_DIR, output_name)

    # 1. Probe video duration & resolution
    res = subprocess.run([ffmpeg_exe, "-i", video_path], capture_output=True, text=True)
    dur = 22.0
    for line in res.stderr.splitlines():
        if "Duration" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
            dur = float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
            break

    print(f"[*] Processing Video: {os.path.basename(video_path)} ({dur:.2f}s)")

    # 2. Generate voice inpainting punch for Peak Arena
    punch_audio = os.path.join(OUTPUT_DIR, "punch_peak_arena.mp3")
    async def make_punch():
        comm = edge_tts.Communicate("Peak Arena app mein", "hi-IN-MadhurNeural", rate="+15%")
        await comm.save(punch_audio)
    asyncio.run(make_punch())

    # 3. Automatic timeline calculation:
    # First 30% duration: raw creator hook & gameplay
    # Middle 35% duration: full-screen Peak Arena app screenshot
    # Final 35% duration: raw creator clutch & CTA
    app_start = round(dur * 0.32, 2)
    app_end = round(dur * 0.65, 2)
    punch_delay_ms = int((app_start - 0.2) * 1000)

    print(f"[*] App Showcase Transition: {app_start}s to {app_end}s")
    print(f"[*] Audio Inpainting Delay: {punch_delay_ms}ms")

    filter_complex = (
        "[0:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black,fps=30[vid_raw];"
        "[1:v]scale=720:1280:flags=lanczos,fps=30[app_screen];"
        f"[vid_raw][app_screen]overlay=0:0:enable='between(t,{app_start},{app_end})'[v];"
        "[0:a]volume=1.0[orig_a];"
        f"[2:a]adelay={punch_delay_ms}|{punch_delay_ms},volume=1.3[punch_a];"
        "[orig_a][punch_a]amix=inputs=2:duration=first:dropout_transition=1[a]"
    )

    cmd = [
        ffmpeg_exe,
        "-y",
        "-t", str(dur),
        "-i", video_path,
        "-i", APP_SCREEN,
        "-i", punch_audio,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "19",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]

    print("[*] Rendering natural-flow reel with Peak Arena app screen & voice inpainting...")
    subprocess.run(cmd, check=True)
    print("=" * 60)
    print(f"SUCCESS! Rendered Reel: {output_path}")
    print(f"File Size: {os.path.getsize(output_path) / (1024 * 1024):.2f} MB")
    print("=" * 60)
    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Peak Arena Reel Hijacker")
    parser.add_argument("--url", help="URL of Instagram reel or YouTube short to hijack")
    parser.add_argument("--file", help="Local video file path to hijack")
    args = parser.parse_args()

    if args.url:
        video_file = download_video(args.url)
    elif args.file:
        video_file = args.file
    else:
        # Default to bundled reference ref_1.mp4
        video_file = os.path.join(REF_DIR, "ref_1.mp4")

    if video_file and os.path.exists(video_file):
        hijack_video(video_file)
    else:
        print("Error: Could not locate video file to process.")
