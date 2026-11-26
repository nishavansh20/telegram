"""
mcp_server.py — Peak Arena Video Editor as an MCP Tool Server (MCP 2.x compatible).
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional, List
from mcp.server.mcpserver import MCPServer

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("PeakArenaMCP")

app = MCPServer("peak-arena-editor")

# Lazy import heavy deps so loading is fast
def _get_processor():
    from video_processor import download_media, apply_edit_instructions, process_reel
    return download_media, apply_edit_instructions, process_reel

def _get_parser():
    from prompt_parser import parse_edit_prompt
    return parse_edit_prompt

def _get_config():
    from config import TEMP_DIR, OUTPUT_DIR, GEMINI_API_KEY, ELEVENLABS_API_KEY
    return TEMP_DIR, OUTPUT_DIR, GEMINI_API_KEY, ELEVENLABS_API_KEY


@app.tool()
def download_reel(url: str) -> str:
    """Download an Instagram Reel or YouTube Short from a URL and return the local video path."""
    download_media, _, _ = _get_processor()
    TEMP_DIR, _, _, _ = _get_config()
    TEMP_DIR.mkdir(exist_ok=True)
    path = download_media(url)
    return json.dumps({"video_path": str(path), "status": "downloaded"})


@app.tool()
def edit_reel(video_path: str, prompt: str, images: Optional[List[str]] = None) -> str:
    """
    Edit a video using a natural-language prompt.
    Supports: replace app screen, replace logo, swap bio outro, add voice over,
    extend video, mute audio, text overlay.
    Provide image paths for visual replacements.
    """
    _, apply_edit_instructions, _ = _get_processor()
    parse_edit_prompt = _get_parser()
    TEMP_DIR, OUTPUT_DIR, GEMINI_API_KEY, _ = _get_config()

    video = Path(video_path)
    if not video.exists():
        return json.dumps({"error": f"video_path not found: {video_path}"})

    img_list = images or []
    instructions = parse_edit_prompt(prompt, img_list, GEMINI_API_KEY)

    if not instructions:
        return json.dumps({"error": "Could not parse any edit instructions from prompt."})

    # Resolve image paths
    img_queue = [Path(p) for p in img_list if Path(p).exists()]
    for instr in instructions:
        if instr.image_path is not None and not instr.image_path.exists():
            if img_queue:
                instr.image_path = img_queue.pop(0)

    output = apply_edit_instructions(video, instructions)
    return json.dumps({"output_path": str(output), "ops_applied": len(instructions), "status": "done"})


@app.tool()
def peak_arena_rebrand(video_path: str, insta_handle: str = "@_maxeddd") -> str:
    """
    Apply the full default Peak Arena rebrand:
    app screen overlay + shield logo + bio outro.
    """
    _, _, process_reel = _get_processor()
    _, _, _, ELEVENLABS_API_KEY = _get_config()

    video = Path(video_path)
    if not video.exists():
        return json.dumps({"error": f"video_path not found: {video_path}"})

    output = process_reel(
        video_path=video,
        replace_bio=True,
        insta_handle=insta_handle,
        elevenlabs_api_key=ELEVENLABS_API_KEY,
    )
    return json.dumps({"output_path": str(output), "status": "done"})


@app.tool()
def replace_default_asset(source_image_path: str, target_asset: str) -> str:
    """
    Replace a default Peak Arena image in assets/.
    target_asset: logo.png, app_overlay_framed.png, app_screen_clean.png, insta_bio_outro.png, or reset_bio.
    """
    from video_processor import update_default_asset
    return json.dumps(update_default_asset(source_image_path, target_asset))


if __name__ == "__main__":
    app.run(transport="stdio")
