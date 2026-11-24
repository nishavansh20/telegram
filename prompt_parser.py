"""
prompt_parser.py — Natural-language edit instructions → structured EditInstruction list.
Uses Gemini Flash to understand freeform user prompts and produce a JSON plan.
Falls back to regex heuristics if Gemini is unavailable.
"""

import json
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EditInstruction:
    """One atomic edit operation on a video."""

    # Type of operation
    # - "replace_region"  : overlay an image over a time range
    # - "add_watermark"   : persistent logo/image overlay
    # - "replace_bio"     : swap bio/outro screen (append or replace end)
    # - "voice_over"      : generate TTS voice over a time range
    # - "extend_video"    : append a new screen/segment at the end
    # - "mute_range"      : duck or mute audio over a range
    # - "text_overlay"    : burn text onto video at a position & time
    op: str

    # Time range (seconds). None = whole video / auto-detect.
    t_start: Optional[float] = None
    t_end: Optional[float] = None

    # Path to a user-supplied image (replacement, overlay, screen, etc.)
    image_path: Optional[Path] = None

    # Text content (for voice_over or text_overlay)
    text: Optional[str] = None

    # Screen position hint: "center", "top-left", "top-right", "bottom", etc.
    position: str = "center"

    # Size as fraction of video height (0.0–1.0). 0 = auto.
    size_fraction: float = 0.0

    # Volume multiplier for mute_range (0 = silent, 0.15 = duck)
    volume: float = 0.0

    # Duration for extend_video / voice_over segments (seconds)
    duration: float = 3.5

    # Raw description from user (kept for debugging)
    raw: str = ""


# ---------------------------------------------------------------------------
# Gemini-based parser
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a video editing assistant for a Telegram bot.
The user sends a text description of edits they want applied to a short vertical video (Reel/Short).
They may also attach images (they will be listed by filename).

Your job: parse the user's message into a JSON array of edit operations.
Each operation must have:
  - "op": one of:
      "replace_region"  – overlay an image over a time window
      "add_watermark"   – persistent image overlay (whole video)
      "replace_bio"     – swap the bio/outro screen at the end
      "voice_over"      – add spoken text over a time window (TTS)
      "extend_video"    – append a new segment/screen at the end
      "mute_range"      – duck or mute audio for a range
      "text_overlay"    – burn text on the video
  - "t_start": float seconds or null (auto-detect)
  - "t_end":   float seconds or null
  - "image_path": filename string or null (the user-supplied image name)
  - "text":    string or null (spoken text or display text)
  - "position": "center" | "top-left" | "top-right" | "bottom" | "top"
  - "size_fraction": 0.0–1.0 (fraction of video height, 0 = auto)
  - "volume": 0.0–1.0 for mute_range (0 = silent)
  - "duration": seconds (for extend_video/voice_over segments)

Rules:
- If user says "replace [X] with [image]" → replace_region, use the image filename they attached.
- If user says "show my app screen" at a time → replace_region.
- If user says "replace logo/watermark" → add_watermark.
- If user says "replace bio / show my Instagram bio" → replace_bio.
- If user says "say [text] / add voice saying [text]" → voice_over with that text.
- If user says "extend / add a screen at the end showing [X]" → extend_video.
- If user says "mute / duck audio from X to Y" → mute_range.
- If user mentions a time like "at 5 seconds", "from 5 to 8", "between 10-15" → extract t_start/t_end.
- If no time given → null (auto-detect).
- Output ONLY valid JSON array. No prose, no markdown, no code fences.

Example output:
[
  {"op":"replace_region","t_start":5.0,"t_end":10.0,"image_path":"my_app.png","text":null,"position":"center","size_fraction":0.72,"volume":0.0,"duration":5.0},
  {"op":"voice_over","t_start":5.0,"t_end":9.0,"image_path":null,"text":"Download Peak Arena now and win real cash!","position":"center","size_fraction":0.0,"volume":0.0,"duration":4.0},
  {"op":"replace_bio","t_start":null,"t_end":null,"image_path":"my_bio.png","text":null,"position":"center","size_fraction":1.0,"volume":0.0,"duration":3.5}
]
"""


def parse_with_gemini(prompt: str, attached_images: List[str], api_key: str) -> List[EditInstruction]:
    """Call Gemini Flash to parse the prompt → list of EditInstruction."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        image_note = ""
        if attached_images:
            image_note = f"\n\nAttached images: {', '.join(attached_images)}"

        response = model.generate_content(
            [_SYSTEM_PROMPT, f"User prompt:\n{prompt}{image_note}"]
        )
        raw = response.text.strip()

        # Strip markdown code fences if model wrapped it
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)

        ops = json.loads(raw)
        return [_dict_to_instruction(o) for o in ops]

    except Exception as e:
        logger.warning(f"Gemini parse failed ({e}), falling back to regex parser")
        return parse_with_regex(prompt, attached_images)


def _dict_to_instruction(d: Dict[str, Any]) -> EditInstruction:
    img = Path(d["image_path"]) if d.get("image_path") else None
    return EditInstruction(
        op=d.get("op", "replace_region"),
        t_start=d.get("t_start"),
        t_end=d.get("t_end"),
        image_path=img,
        text=d.get("text"),
        position=d.get("position", "center"),
        size_fraction=float(d.get("size_fraction", 0.0)),
        volume=float(d.get("volume", 0.0)),
        duration=float(d.get("duration", 3.5)),
        raw=str(d),
    )


# ---------------------------------------------------------------------------
# Regex heuristic fallback (no API key needed)
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(
    r"(?:from\s+)?(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?\s*[-–to]+\s*(\d+(?:\.\d+)?)\s*s",
    re.IGNORECASE
)
_SINGLE_TIME_RE = re.compile(
    r"(?:at|from)\s+(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?",
    re.IGNORECASE
)


def _extract_time(text: str):
    m = _TIME_RE.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    m2 = _SINGLE_TIME_RE.search(text)
    if m2:
        t = float(m2.group(1))
        return t, t + 5.0
    return None, None


def parse_with_regex(prompt: str, attached_images: List[str]) -> List[EditInstruction]:
    """Heuristic keyword parser — no API key."""
    instructions: List[EditInstruction] = []
    low = prompt.lower()
    t_s, t_e = _extract_time(prompt)

    # Image to use (first attached, if any)
    first_img = Path(attached_images[0]) if attached_images else None

    # Bio replacement
    if any(w in low for w in ["bio", "instagram bio", "my profile", "insta page", "my bio"]):
        instructions.append(EditInstruction(
            op="replace_bio",
            image_path=first_img,
            duration=3.5,
            raw=prompt
        ))

    # App screen / image overlay
    if any(w in low for w in ["app screen", "my app", "replace screen", "show my app",
                               "replace their app", "replace the app", "replace popup"]):
        img = first_img
        # If multiple images, the first replace_bio consumed one — use next for app
        if first_img and len(attached_images) > 1:
            img = Path(attached_images[1])
        instructions.append(EditInstruction(
            op="replace_region",
            t_start=t_s,
            t_end=t_e,
            image_path=img,
            position="center",
            size_fraction=0.72,
            raw=prompt
        ))

    # Watermark / logo
    if any(w in low for w in ["watermark", "logo", "replace logo", "my logo", "shield"]):
        instructions.append(EditInstruction(
            op="add_watermark",
            image_path=first_img,
            position="top-right",
            raw=prompt
        ))

    # Voice over
    voice_match = re.search(
        r'(?:say|voice[_ ]?over|add voice|speak)\s+["\']?(.+?)["\']?\s*(?:over|from|at|$)',
        prompt, re.IGNORECASE
    )
    if voice_match:
        instructions.append(EditInstruction(
            op="voice_over",
            t_start=t_s,
            t_end=t_e,
            text=voice_match.group(1).strip(),
            raw=prompt
        ))

    # Extend video
    if any(w in low for w in ["extend", "add at end", "add screen at end", "append"]):
        instructions.append(EditInstruction(
            op="extend_video",
            image_path=first_img,
            duration=3.5,
            raw=prompt
        ))

    # Text overlay
    text_match = re.search(
        r'(?:add text|show text|overlay text)\s+["\']?(.+?)["\']?\s*(?:at|from|$)',
        prompt, re.IGNORECASE
    )
    if text_match:
        instructions.append(EditInstruction(
            op="text_overlay",
            t_start=t_s,
            t_end=t_e,
            text=text_match.group(1).strip(),
            position="bottom",
            raw=prompt
        ))

    # Mute / duck
    if any(w in low for w in ["mute", "silence", "duck audio", "lower audio"]):
        vol = 0.0 if "mute" in low or "silence" in low else 0.15
        instructions.append(EditInstruction(
            op="mute_range",
            t_start=t_s,
            t_end=t_e,
            volume=vol,
            raw=prompt
        ))

    if not instructions:
        # Generic: if image attached, do replace_region
        if first_img:
            instructions.append(EditInstruction(
                op="replace_region",
                t_start=t_s,
                t_end=t_e,
                image_path=first_img,
                position="center",
                size_fraction=0.72,
                raw=prompt
            ))

    return instructions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_edit_prompt(
    prompt: str,
    attached_images: List[str],
    gemini_api_key: str = ""
) -> List[EditInstruction]:
    """
    Parse user edit prompt → list of EditInstruction.
    Uses Gemini if api_key provided, else regex heuristics.
    """
    if gemini_api_key:
        return parse_with_gemini(prompt, attached_images, gemini_api_key)
    return parse_with_regex(prompt, attached_images)
