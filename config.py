

import os
from pathlib import Path
from dotenv import load_dotenv

from logger import get_logger

logger = get_logger("CONFIG")


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
ASSETS_DIR = ROOT_DIR / "assets"

for folder in (DATA_DIR, LOG_DIR, ASSETS_DIR):
    folder.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT_DIR / ".env")


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.critical(f"Missing environment variable: {name}")
        raise RuntimeError(f"Missing .env variable: {name}")
    return value


BOT_TOKEN = required("BOT_TOKEN")
OWNER_ID = int(required("OWNER_ID"))
OWNER_USERNAME = required("OWNER_USERNAME")
OWNER_NAME = os.getenv("OWNER_NAME", "𝑶𝑮𝑮𝒀 𝑷𝑹𝑶𝑶")

START_PHOTO = "OGGY.jpg"
START_PHOTO_PATH = ASSETS_DIR / START_PHOTO

if not START_PHOTO_PATH.exists():
    START_PHOTO_PATH = ROOT_DIR / "OGGY.jpg"
    if not START_PHOTO_PATH.exists():
        logger.warning(f"START_PHOTO not found at {START_PHOTO_PATH}")
        START_PHOTO_PATH = ASSETS_DIR / "default.jpg"

API_ID = int(required("API_ID"))
API_HASH = required("API_HASH")
SESSION_STRING = required("SESSION_STRING")

DEFAULT_LIMIT = int(os.getenv("DEFAULT_LIMIT", "100"))
PREMIUM_LIMIT = int(os.getenv("PREMIUM_LIMIT", "5000"))

BOT_USERNAME = os.getenv("BOT_USERNAME", "OggyPrimeBotrobot")

# Multi-API support: primary + owner-added extras
API_BASE_URL = os.getenv("API_BASE_URL", "https://check.yzio.app")
# Extra API URLs (owner-added), stored as comma-separated in env
EXTRA_API_URLS_RAW = os.getenv("EXTRA_API_URLS", "")

def get_all_api_urls() -> list:
    """Return list of all API URLs (primary + extras)."""
    urls = [API_BASE_URL]
    if EXTRA_API_URLS_RAW:
        for u in EXTRA_API_URLS_RAW.split(","):
            u = u.strip()
            if u and u not in urls:
                urls.append(u)
    return urls

TEST_CARD = os.getenv("TEST_CARD", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

DATABASE_URL = required("DATABASE_URL")
USE_POSTGRES = os.getenv("USE_POSTGRES", "true").lower() == "true"
DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "bot.db"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger.info("Configuration loaded successfully.")
logger.info(f"Database : PostgreSQL")
logger.info(f"API      : {API_BASE_URL}")
logger.info(f"LogLevel : {LOG_LEVEL}")
logger.info(f"Owner ID : {OWNER_ID}")
logger.info(f"Owner Username : {OWNER_USERNAME}")
logger.info(f"Owner Name : {OWNER_NAME}")
logger.info(f"Start Photo : {START_PHOTO_PATH}")
