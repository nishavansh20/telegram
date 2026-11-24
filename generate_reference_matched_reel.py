import os
import subprocess
import imageio_ffmpeg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CARDS_DIR = os.path.join(OUTPUT_DIR, "demo_cards")

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

clean_video = os.path.join(OUTPUT_DIR, "clean_gameplay.mp4")
voiceover = os.path.join(OUTPUT_DIR, "peak_arena_voiceover_synced.mp3")

top_bar = os.path.join(CARDS_DIR, "top_bar_pro.png")
bottom_bar = os.path.join(CARDS_DIR, "bottom_bar_pro.png")
card_hook = os.path.join(CARDS_DIR, "card_hook.png")
card_br = os.path.join(CARDS_DIR, "card_br_solo.png")
card_cs = os.path.join(CARDS_DIR, "card_clash_squad.png")
card_payout = os.path.join(CARDS_DIR, "card_payout_receipt.png")
card_cta = os.path.join(CARDS_DIR, "card_final_cta.png")

output_final = os.path.join(OUTPUT_DIR, "PeakArena_Reference_Promo_Reel.mp4")

DURATION = 26.50

# Center of gameplay zone:
# Top bar: y=0 to 420
# Bottom bar: y=1500 to 1920
# Gameplay zone: y=420 to 1500 (height: 1080px)
# Center Y for cards: 420 + (1080 - h) / 2

filter_complex = (
    # Scale background video to 1080x1920
    "[0:v]scale=1080:1920:flags=lanczos,fps=30[bg0];"
    # Permanent Top Bar covering competitor overlays for entire reel
    "[bg0][2:v]overlay=x=0:y=0[bg1];"
    # Permanent Bottom Bar covering competitor overlays for entire reel
    "[bg1][3:v]overlay=x=0:y=1500[bg2];"
    # Scene 1: Hook card (0 to 4.5s)
    "[bg2][4:v]overlay=x=(1080-w)/2:y=420+(1080-h)/2:enable='between(t,0,4.5)'[bg3];"
    # Scene 2: BR Solo Card (4.5s to 11.5s) - ₹15 Entry, ₹12/kill, ₹700 Pool
    "[bg3][5:v]overlay=x=(1080-w)/2:y=420+(1080-h)/2:enable='between(t,4.5,11.5)'[bg4];"
    # Scene 3: Clash Squad Card (11.5s to 17.0s) - ₹20 Entry, ₹35 Win
    "[bg4][6:v]overlay=x=(1080-w)/2:y=420+(1080-h)/2:enable='between(t,11.5,17.0)'[bg5];"
    # Scene 4: Payout Receipt Card (17.0s to 21.5s) - Instant UPI ₹700
    "[bg5][7:v]overlay=x=(1080-w)/2:y=420+(1080-h)/2:enable='between(t,17.0,21.5)'[bg6];"
    # Scene 5: Final CTA Card (21.5s to 26.50s) - Promo code & Bio Link
    "[bg6][8:v]overlay=x=(1080-w)/2:y=420+(1080-h)/2:enable='between(t,21.5,26.5)'[v];"
    # Audio ducking: voiceover prominent, game sfx in background
    "[0:a]volume=0.15[game_sfx];"
    "[1:a]volume=1.2[vo];"
    "[game_sfx][vo]amix=inputs=2:duration=first:dropout_transition=2[a]"
)

cmd = [
    ffmpeg_exe,
    "-y",
    "-t", str(DURATION),
    "-i", clean_video,
    "-i", voiceover,
    "-i", top_bar,
    "-i", bottom_bar,
    "-i", card_hook,
    "-i", card_br,
    "-i", card_cs,
    "-i", card_payout,
    "-i", card_cta,
    "-filter_complex", filter_complex,
    "-map", "[v]",
    "-map", "[a]",
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-c:a", "aac",
    "-b:a", "192k",
    output_final
]

print("Rendering 100% clean Peak Arena promo reel...")
subprocess.run(cmd, check=True)
print(f"SUCCESS! Rendered: {output_final}")
