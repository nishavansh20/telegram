import numpy as np
from typing import List, Tuple, Optional
from moviepy import VideoFileClip


def detect_app_screen_ranges(
    clip: VideoFileClip,
    sample_interval: float = 0.5,
    min_duration: float = 1.0
) -> List[Tuple[float, float]]:
    """
    Intelligently detect timestamps where an app screenshot or popup card
    appears over gameplay in a vertical Reel.
    """
    dur = clip.duration
    samples = []

    # Sample frames across video
    for t in np.arange(0, dur, sample_interval):
        try:
            frame = clip.get_frame(t)
            h, w, _ = frame.shape

            # Focus on center area where app screens & popups appear
            y1, y2 = int(h * 0.22), int(h * 0.78)
            x1, x2 = int(w * 0.15), int(w * 0.85)
            center = frame[y1:y2, x1:x2]

            # 1. White / Light card ratio (e.g. withdrawal popup, transaction screen)
            white_ratio = float(np.mean((center[:, :, 0] > 195) & (center[:, :, 1] > 195) & (center[:, :, 2] > 195)))

            # 2. Dark card ratio (dark mode app interface)
            dark_ratio = float(np.mean((center[:, :, 0] < 40) & (center[:, :, 1] < 40) & (center[:, :, 2] < 45)))

            # 3. Flatness: 2D UI has lower color variance across blocks compared to 3D foliage/sky
            std_val = float(np.std(center))

            is_app_frame = (white_ratio > 0.09) or (dark_ratio > 0.40 and std_val < 50.0)
            samples.append((t, is_app_frame))
        except Exception:
            continue

    # Group consecutive detections into (start, end) ranges
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

    return ranges


def detect_bio_screen(
    clip: VideoFileClip,
    check_duration: float = 4.0
) -> bool:
    """
    Check if the last few seconds of the reel show an Instagram profile / bio screen.
    """
    dur = clip.duration
    if dur < check_duration:
        return False

    start_check = max(0.0, dur - check_duration)
    bio_votes = 0
    total_checks = 0

    for t in np.arange(start_check, dur, 0.5):
        total_checks += 1
        try:
            frame = clip.get_frame(t)
            h, w, _ = frame.shape
            # In an Instagram bio screen, the top header has profile avatar & stats
            top_header = frame[int(h * 0.1):int(h * 0.35), :]
            # Bio screen has very dark background on dark mode or solid white on light mode
            dark_bg = np.mean(top_header < 30) > 0.55
            white_bg = np.mean(top_header > 230) > 0.55
            if dark_bg or white_bg:
                bio_votes += 1
        except Exception:
            continue

    # If more than half the sampled tail frames look like a profile UI
    return total_checks > 0 and (bio_votes / total_checks) >= 0.5
