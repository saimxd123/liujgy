import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.LIGHTRED_EX,
    }
except Exception:
    COLORS = {}

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

BOT_LOG = os.path.join(LOG_DIR, "bot.log")
ERR_LOG = os.path.join(LOG_DIR, "errors.log")


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        original = record.levelname
        if COLORS:
            color = COLORS.get(record.levelno, "")
            record.levelname = f"{color}{original:<8}{Style.RESET_ALL}"
        else:
            record.levelname = f"{original:<8}"
        message = super().format(record)
        record.levelname = original
        return message


FORMAT = "%(asctime)s │ %(levelname)s │ %(name)-12s │ %(message)s"
DATEFMT = "%H:%M:%S"
console_formatter = ColoredFormatter(FORMAT, DATEFMT)
file_formatter = logging.Formatter(FORMAT, DATEFMT)


class FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


_shared_handlers = None

def _build_handlers():
    """Build the shared handler set ONCE and reuse across all loggers."""
    console = FlushStreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(console_formatter)

    # full log
    bot_handler = RotatingFileHandler(
        BOT_LOG, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    bot_handler.setLevel(logging.INFO)
    bot_handler.setFormatter(file_formatter)

    # error-only log
    err_handler = RotatingFileHandler(
        ERR_LOG, maxBytes=1024 * 1024, backupCount=1, encoding="utf-8"
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(file_formatter)

    return [console, bot_handler, err_handler]


def get_logger(name: str):
    global _shared_handlers
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    if _shared_handlers is None:
        _shared_handlers = _build_handlers()

    logger.setLevel(logging.INFO)
    for h in _shared_handlers:
        logger.addHandler(h)

    logger.propagate = False
    return logger


class Timer:
    def __init__(self):
        self.start = time.perf_counter()

    @property
    def elapsed(self):
        return round(time.perf_counter() - self.start, 3)


def print_banner():
    get_logger("SYSTEM").warning("𝑶𝑮𝑮𝒀 PRIME BOT started")
