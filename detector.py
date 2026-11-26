"""
detector.py — Low-memory FFmpeg-piped CV popup & bio screen detection.
"""

import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Union
import numpy as np
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


def probe_video_info(video_path: Union[str, Path]) -> Tuple[float, int, int, bool]:
    """Return (duration_sec, width, height, has_audio) via a single lightweight ffmpeg probe."""
    res = subprocess.run(
        [FFMPEG_EXE, "-i", str(video_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    info = res.stderr or ""

    dur = 0.0
    m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    if m_dur:
        dur = int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + float(m_dur.group(3))

    vw, vh = 1080, 1920
    m_res = re.search(r"Stream #.*Video:.*?,\s*(\d{2,5})x(\d{2,5})", info)
    if m_res:
        vw, vh = int(m_res.group(1)), int(m_res.group(2))

    has_audio = bool(re.search(r"Stream #.*Audio:", info))
    return dur, vw, vh, has_audio


def _iter_ffmpeg_frames(
    video_path: Union[str, Path],
    fps: float,
    target_w: int = 270,
    start_sec: float = 0.0,
    duration_sec: Optional[float] = None,
):
    """Yield downscaled RGB frames from ffmpeg stdout pipe using ~10 MB RAM."""
    _, orig_w, orig_h, _ = probe_video_info(video_path)
    target_h = max(2, int(round(orig_h * (target_w / max(1, orig_w))) // 2 * 2))

    cmd = [FFMPEG_EXE, "-hide_banner", "-loglevel", "error"]
    if start_sec > 0:
        cmd.extend(["-ss", f"{start_sec:.2f}"])
    cmd.extend(["-i", str(video_path)])
    if duration_sec is not None:
        cmd.extend(["-t", f"{duration_sec:.2f}"])
    cmd.extend([
        "-vf", f"fps={fps},scale={target_w}:{target_h}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ])

    frame_bytes = target_w * target_h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    idx = 0
    try:
        while proc.stdout is not None:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((target_h, target_w, 3))
            yield start_sec + idx / fps, frame
            idx += 1
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()


def _is_app_frame(frame: np.ndarray) -> bool:
    h, w, _ = frame.shape
    center = frame[int(h * 0.22):int(h * 0.78), int(w * 0.15):int(w * 0.85)]
    white_ratio = float(np.mean((center[:, :, 0] > 195) & (center[:, :, 1] > 195) & (center[:, :, 2] > 195)))
    dark_ratio = float(np.mean((center[:, :, 0] < 40) & (center[:, :, 1] < 40) & (center[:, :, 2] < 45)))
    std_val = float(np.std(center))
    return (white_ratio > 0.09) or (dark_ratio > 0.40 and std_val < 50.0)


def detect_app_screen_ranges(
    source,
    sample_interval: float = 0.5,
    min_duration: float = 1.8,
    max_duration: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """
    Detect timestamps where an app screenshot or popup card appears over gameplay.
    Accepts a video file Path/str (fast, low-RAM FFmpeg pipe) or a MoviePy VideoFileClip.
    """
    samples = []
    if isinstance(source, (str, Path)):
        dur, _, _, _ = probe_video_info(source)
        if max_duration is not None:
            dur = min(dur, max_duration)
        fps = 1.0 / max(0.1, sample_interval)
        for t, frame in _iter_ffmpeg_frames(source, fps=fps, duration_sec=dur):
            samples.append((t, _is_app_frame(frame)))
    else:
        dur = float(source.duration or 0.0)
        for t in np.arange(0, dur, sample_interval):
            try:
                samples.append((float(t), _is_app_frame(source.get_frame(t))))
            except Exception:
                continue

    ranges = []
    in_range = False
    start_t = 0.0

    for t, is_app in samples:
        if is_app and not in_range:
            in_range = True
            start_t = t
        elif not is_app and in_range:
            in_range = False
            if (t - start_t) >= min_duration:
                ranges.append((round(start_t, 1), round(t, 1)))

    if in_range and (dur - start_t) >= min_duration:
        ranges.append((round(start_t, 1), round(dur, 1)))

    # Merge nearby popup detections (<= 1.0s gap) to prevent flickering
    merged: List[Tuple[float, float]] = []
    for s, e in ranges:
        if merged and (s - merged[-1][1]) <= 1.0:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    return merged


def detect_bio_screen(
    source,
    check_duration: float = 4.0,
    max_duration: Optional[float] = None,
) -> bool:
    """
    Check if the last few seconds of the reel show an Instagram profile / bio screen.
    Accepts a video file Path/str (fast FFmpeg pipe) or a MoviePy VideoFileClip.
    """
    bio_votes = 0
    total_checks = 0

    def _is_bio(frame: np.ndarray) -> bool:
        h = frame.shape[0]
        top_header = frame[int(h * 0.1):int(h * 0.35), :]
        dark_bg = np.mean(top_header < 30) > 0.55
        white_bg = np.mean(top_header > 230) > 0.55
        return bool(dark_bg or white_bg)

    if isinstance(source, (str, Path)):
        dur, _, _, _ = probe_video_info(source)
        if max_duration is not None:
            dur = min(dur, max_duration)
        if dur < check_duration:
            return False
        start_check = max(0.0, dur - check_duration)
        for _, frame in _iter_ffmpeg_frames(source, fps=2.0, start_sec=start_check, duration_sec=check_duration):
            total_checks += 1
            if _is_bio(frame):
                bio_votes += 1
    else:
        dur = float(source.duration or 0.0)
        if dur < check_duration:
            return False
        start_check = max(0.0, dur - check_duration)
        for t in np.arange(start_check, dur, 0.5):
            total_checks += 1
            try:
                if _is_bio(source.get_frame(t)):
                    bio_votes += 1
            except Exception:
                continue

    return total_checks > 0 and (bio_votes / total_checks) >= 0.5
