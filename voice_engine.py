import os
import subprocess
from pathlib import Path
from typing import Optional
import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


def extract_reference_audio(video_audio_path: Path, output_wav: Path, duration: float = 6.0) -> Path:
    """Extract first N seconds of clean creator voice to use as reference for voice cloning."""
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-i", str(video_audio_path),
        "-t", str(duration),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "24000",
        "-ac", "1",
        str(output_wav)
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output_wav


def generate_cloned_voice(
    text: str,
    reference_audio: Path,
    output_audio: Path,
    elevenlabs_api_key: Optional[str] = None
) -> Optional[Path]:
    """
    Generate voice speaking the text in the creator's voice:
    1. If ELEVENLABS_API_KEY is provided: uses instant cloud voice cloning.
    2. If local PyTorch XTTS is installed: uses local zero-shot TTS.
    3. Returns None if cloning not configured (leaving original voice clean).
    """
    # 1. ElevenLabs API Instant Voice Clone
    if elevenlabs_api_key and elevenlabs_api_key.strip():
        try:
            import requests
            headers = {"xi-api-key": elevenlabs_api_key.strip()}
            # Add instant voice clone
            url = "https://api.elevenlabs.io/v1/voices/add"
            with open(reference_audio, "rb") as f:
                files = {"files": f}
                data = {
                    "name": "ReelCreatorVoice",
                    "description": "Auto cloned voice from reel"
                }
                res = requests.post(url, headers=headers, data=data, files=files)
                if res.status_code == 200:
                    voice_id = res.json().get("voice_id")
                    # Generate speech
                    tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                    payload = {
                        "text": text,
                        "model_id": "eleven_multilingual_v2",
                        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}
                    }
                    tts_res = requests.post(tts_url, json=payload, headers=headers)
                    if tts_res.status_code == 200:
                        with open(output_audio, "wb") as out_f:
                            out_f.write(tts_res.content)
                        return output_audio
        except Exception as e:
            print(f"ElevenLabs voice cloning failed: {e}")

    # 2. Local PyTorch Zero-Shot Clone (if torch & TTS installed)
    try:
        from TTS.api import TTS
        tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2")
        tts.tts_to_file(
            text=text,
            speaker_wav=str(reference_audio),
            language="hi",
            file_path=str(output_audio)
        )
        return output_audio
    except Exception:
        pass

    return None
