import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env if present
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Allowed user IDs (comma separated integers)
_allowed_raw = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = [int(x.strip()) for x in _allowed_raw.split(",") if x.strip().isdigit()]

# Directories
ASSETS_DIR = BASE_DIR / "assets"
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

LOGO_PATH = ASSETS_DIR / "logo.png"

DEFAULT_OUTRO_TITLE = os.getenv("DEFAULT_OUTRO_TITLE", "PEAK ARENA")
DEFAULT_OUTRO_SUBTITLE = os.getenv("DEFAULT_OUTRO_SUBTITLE", "Daily Free Fire & BGMI Tournaments • Instant UPI Payouts")
DEFAULT_OUTRO_LINK = os.getenv("DEFAULT_OUTRO_LINK", "Download Link in Bio / Channel")
DEFAULT_INSTA_HANDLE = os.getenv("DEFAULT_INSTA_HANDLE", "@_maxeddd")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# AGY Integration
AGY_LS_EXE = os.getenv("AGY_LS_EXE", r"C:\Users\vansh\AppData\Local\Programs\antigravity\resources\bin\language_server.exe")
AGY_CLI_PATH = os.getenv("AGY_CLI_PATH", r"C:\Users\vansh\.gemini\antigravity\bin\agentapi.bat")
AGY_BRAIN_DIR = Path(os.getenv("AGY_BRAIN_DIR", r"C:\Users\vansh\.gemini\antigravity\brain"))
AGY_DEFAULT_MODEL = os.getenv("AGY_DEFAULT_MODEL", "gemini-4-hydrogen-xhigh")
GEMINI_CLOUD_MODEL = os.getenv("GEMINI_CLOUD_MODEL", "gemini-4-hydrogen")
GEMINI_FALLBACK_MODELS = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash")

# 24/7 Health & Cron Ping Configuration
HEALTH_PORT = int(os.getenv("PORT", os.getenv("HEALTH_PORT", "8080")))
ENABLE_HEALTH_SERVER = os.getenv("ENABLE_HEALTH_SERVER", "true").lower() == "true"


