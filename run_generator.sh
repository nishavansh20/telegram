#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "====================================================================="
echo "               PEAK ARENA VIRAL REEL ENGINE"
echo "====================================================================="
echo "[1] Hijack Reel from URL (Paste Instagram / YouTube Shorts link)"
echo "[2] Hijack Reference Reel (Natural flow, voice inpainting, no extra bars)"
echo "[3] Generate Esports Tournament Reel (With match cards + voiceover)"
echo "====================================================================="
read -p "Enter option (1, 2, or 3, default is 1): " choice

PYTHON_BIN="python3"
if [ -f "venv/bin/python" ]; then
    PYTHON_BIN="venv/bin/python"
fi

if [ "$choice" = "1" ]; then
    read -p "Paste Reel / Shorts URL: " reel_url
    echo "Downloading and hijacking reel..."
    "$PYTHON_BIN" auto_reel_hijacker.py --url "$reel_url"
elif [ "$choice" = "3" ]; then
    echo "Generating tournament promo reel..."
    "$PYTHON_BIN" generate_reference_matched_reel.py
else
    echo "Hijacking reference reel..."
    "$PYTHON_BIN" auto_reel_hijacker.py
fi

echo "====================================================================="
echo "Done! Check output folder for rendered reel."
echo "====================================================================="
