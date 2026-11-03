import os
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("CONFIG")


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────
def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.critical(f"Missing environment variable: {name}")
        raise RuntimeError(f"Missing .env variable: {name}")
    return value


def optional(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


# ─────────────────────────────────────────────────────────
# Required
# ─────────────────────────────────────────────────────────
BOT_TOKEN = required("BOT_TOKEN")


# ─────────────────────────────────────────────────────────
# Bot identity
# ─────────────────────────────────────────────────────────
BOT_USERNAME = optional("BOT_USERNAME", "OggyPrimeBot").lstrip("@")
BOT_NAME = optional("BOT_NAME", "OGGY PRIME BOT")


# ─────────────────────────────────────────────────────────
# Owner
# ─────────────────────────────────────────────────────────
OWNER_ID = int(optional("OWNER_ID", "8919487892"))
OWNER_USERNAME = optional("OWNER_USERNAME", "oggyproo").lstrip("@")
OWNER_NAME = optional("OWNER_NAME", "OGGY")


# ─────────────────────────────────────────────────────────
# Support / links
# ─────────────────────────────────────────────────────────
SUPPORT_USERNAME = optional("SUPPORT_USERNAME", OWNER_USERNAME).lstrip("@")


# ─────────────────────────────────────────────────────────
# Userbot (optional — leave blank if not used)
# ─────────────────────────────────────────────────────────
API_ID = optional("API_ID", "")
API_HASH = optional("API_HASH", "")
SESSION_STRING = optional("SESSION_STRING", "")


# ─────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────
DATABASE_URL = optional("DATABASE_URL", "")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///bot.db"
    logger.warning(
        "DATABASE_URL not set — using SQLite at ./bot.db. "
        "Bot will work; data resets if Render wipes the disk."
    )

USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))


# ─────────────────────────────────────────────────────────
# API / gate helpers
# ─────────────────────────────────────────────────────────
API_BASE_URL = optional("API_BASE_URL", "")


# ─────────────────────────────────────────────────────────
# Log / force-join channels (only used if your code imports them)
# ─────────────────────────────────────────────────────────
LOG_CHANNEL_ID = optional("LOG_CHANNEL_ID", "")
LOG_CHANNEL_USERNAME = optional("LOG_CHANNEL_USERNAME", "OGGYxLOGS").lstrip("@")

CHANNEL_ID = optional("CHANNEL_ID", "")
CHANNEL_USERNAME = optional("CHANNEL_USERNAME", "oggyproo").lstrip("@")

GROUP_ID = optional("GROUP_ID", "")
GROUP_USERNAME = optional("GROUP_USERNAME", "oggyproo_group").lstrip("@")

LOGS_CHAT_ID = optional("LOGS_CHAT_ID", "")
LOGS_CHAT_USERNAME = optional("LOGS_CHAT_USERNAME", "OGGYxLOGS").lstrip("@")

FORCE_JOIN_IMAGE = optional("FORCE_JOIN_IMAGE", "OGGY.jpg")


# ─────────────────────────────────────────────────────────
# Banner photo (graceful fallback to text if missing)
# ─────────────────────────────────────────────────────────
_photo_candidates = [
    "OGGY.jpg", "OGGY.jpeg", "OGGY.png",
    "assets/OGGY.jpg", "assets/OGGY.jpeg", "assets/OGGY.png",
]

START_PHOTO = None
for _p in _photo_candidates:
    if os.path.isfile(_p):
        START_PHOTO = _p
        break

START_PHOTO_PATH = START_PHOTO

if not START_PHOTO:
    logger.warning(
        "START_PHOTO not found — /start will fall back to text. "
        "Add OGGY.jpg to the repo root to enable the banner."
    )
