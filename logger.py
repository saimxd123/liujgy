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


def get_logger(name: str):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.WARNING)

    console = FlushStreamHandler(sys.stdout)
    console.setLevel(logging.WARNING)
    console.setFormatter(console_formatter)

    error_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "errors.log"),
        maxBytes=512 * 1024,
        backupCount=1,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)

    logger.addHandler(console)
    logger.addHandler(error_handler)
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
