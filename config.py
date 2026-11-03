import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("CONFIG")


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.critical(f"Missing environment variable: {name}")
        raise RuntimeError(f"Missing .env variable: {name}")
    return value


def optional(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


# ── Required ──────────────────────────────────────────────
BOT_TOKEN = required("BOT_TOKEN")

# ── Owner ────────────────────────────────────────────────
OWNER_ID = int(optional("OWNER_ID", "8919487892"))
OWNER_USERNAME = optional("OWNER_USERNAME", "oggyproo").lstrip("@")
OWNER_NAME = optional("OWNER_NAME", "OGGY")

# ── Userbot (optional — leave blank) ─────────────────────
API_ID = optional("API_ID", "")
API_HASH = optional("API_HASH", "")
SESSION_STRING = optional("SESSION_STRING", "")

# ── Database (fallback to SQLite) ────────────────────────
DATABASE_URL = optional("DATABASE_URL", "")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///bot.db"
    logger.warning(
        "DATABASE_URL not set — using SQLite at ./bot.db. "
        "Add a DATABASE_URL for persistence across deploys."
    )

# ── Banner photo ─────────────────────────────────────────
_photo_candidates = [
    "OGGY.jpg", "OGGY.jpeg", "OGGY.png",
    "assets/OGGY.jpg", "assets/OGGY.jpeg", "assets/OGGY.png",
]
START_PHOTO = None
for _p in _photo_candidates:
    if os.path.isfile(_p):
        START_PHOTO = _p
        break

START_PHOTO_PATH = START_PHOTO  # alias

if not START_PHOTO:
    logger.warning(
        "START_PHOTO not found — /start will fall back to text. "
        "Add OGGY.jpg to the repo root to enable the banner."
    )
