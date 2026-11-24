# Peak Arena Viral Reel Automation & Hijacker Engine

Automated reel pipeline that takes any gaming video URL or clip, preserves the original creator's real voice and gameplay flow (no arbitrary top/bottom/middle borders), in-paints "Peak Arena" into the audio track, and seamlessly swaps competitor app screens for full-screen Peak Arena tournament app UI.

## Features
1. **100% Natural Flow**:
   - Zero added headers, footers, or cards over gameplay.
   - Gameplay plays completely unaltered, just like the original video.
2. **App Screen Swap**:
   - When the creator introduces the app, video smoothly cuts to Peak Arena's full-screen vertical mobile dashboard:
     - Free Fire Bermuda Solo (Entry ₹15, Per Kill ₹12, Prize Pool ₹700)
     - Clash Squad 4v4 Ranked (Entry ₹20, Win ₹35)
     - Wallet Balance: ₹750
     - Instant 5-Min UPI Withdrawal Proof
     - Promo Code: `PEAK10`
3. **Voice In-Painting**:
   - Retains 100% of the original speaker's real human voice and game sounds.
   - Slices in a matched vocal punch for "Peak Arena app mein" right as the app is shown.
4. **URL Downloader & Processor**:
   - Pass any Instagram reel URL or YouTube Shorts URL directly.

## Usage
Double-click `run_generator.bat`:
- **Option 1**: Paste any reel URL (`https://www.instagram.com/reel/...`) to download and hijack it.
- **Option 2**: Run on bundled reference reel.
- **Option 3**: Generate studio-style tournament promo reel with full custom match cards.

Or via command line:
```powershell
.\venv\Scripts\python.exe auto_reel_hijacker.py --url "https://www.instagram.com/reel/DfthLTIt6-p/"
```
Rendered output is saved in `output/PeakArena_Hijacked_Reel.mp4`.
