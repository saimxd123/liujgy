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

# ── Owner (defaulted to your values) ─────────────────────
OWNER_ID = int(optional("OWNER_ID", "8919487892"))
OWNER_USERNAME = optional("OWNER_USERNAME", "oggyproo").lstrip("@")
OWNER_NAME = optional("OWNER_NAME", "OGGY")

# ── Userbot (NOT NEEDED unless you add Pyrogram features) ─
API_ID = optional("API_ID", "")
API_HASH = optional("API_HASH", "")
SESSION_STRING = optional("SESSION_STRING", "")

# ── Database ─────────────────────────────────────────────
DATABASE_URL = optional("DATABASE_URL", "")
if not DATABASE_URL:
    logger.warning(
        "DATABASE_URL not set — DB features will fail unless your code "
        "falls back to SQLite."
    )

# ── Banner photo (graceful fallback) ─────────────────────
_photo_candidates = [
    "OGGY.jpg", "OGGY.jpeg", "OGGY.png",
    "assets/OGGY.jpg", "assets/OGGY.jpeg", "assets/OGGY.png",
]
START_PHOTO_PATH = None
for _p in _photo_candidates:
    if os.path.isfile(_p):
        START_PHOTO_PATH = _p
        break

if not START_PHOTO_PATH:
    logger.warning(
        "START_PHOTO not found — /start will fall back to text. "
        "Add OGGY.jpg to the repo root to restore the banner."
    )
