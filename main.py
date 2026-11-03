import asyncio
import os
import sys
import time
from datetime import datetime

from telegram import Update, LinkPreviewOptions
from telegram.ext import Application, ContextTypes
from telegram.error import RetryAfter, TimedOut, NetworkError
from telegram.request import HTTPXRequest

from config import (
    BOT_TOKEN,
    OWNER_ID,
    OWNER_USERNAME,
    OWNER_NAME,
    START_PHOTO_PATH,
)

from logger import get_logger, print_banner
from handlers import register_handlers
from gates import register_gates
from core.errors import global_error_handler
from database.db import is_bot_locked
from ui.emojis import PremiumEmoji as E

logger = get_logger(__name__)

BOT_START_TIME = datetime.now()


async def startup(app: Application):
    """Run on bot startup."""
    logger.info("=" * 60)
    logger.info("𝑶𝑮𝑮𝒀'𝑺 𝑷𝑹𝑰𝑴𝑬 𝑩𝑶𝑻")
    logger.info("Built by @oggyproo")
    logger.info("=" * 60)

    try:
        from handlers.premium_notify import start_premium_notification_worker
        start_premium_notification_worker(app.bot)
        logger.info("✅ Premium notification scheduler started")
    except ImportError as e:
        logger.info(f"ℹ️ Premium notification module not found: {e}")

    logger.info("🚀 All workers started successfully")


async def shutdown(app: Application):
    """Run on bot shutdown."""
    logger.info("𝑶𝑮𝑮𝒀'𝑺 𝑷𝑹𝑰𝑴𝑬 𝑩𝑶𝑻 offline ")


class LockedApplication(Application):
    """Application with global lock check."""

    async def process_update(self, update, *args, **kwargs):
        if update.effective_user:
            user_id = update.effective_user.id

            if user_id == OWNER_ID:
                return await super().process_update(update, *args, **kwargs)

            if update.message and update.message.text:
                text = update.message.text
                if text.startswith("/lock") or text.startswith("/unlock"):
                    return await super().process_update(
                        update,
                        *args,
                        **kwargs
                    )

            if is_bot_locked():
                if update.message:
                    await update.message.reply_text(
                        f"""
{E.LOCK} ⌠ 𝘽𝙊𝙏 𝙄𝙎 𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
Bot is currently under maintenance by the owner.

Please wait until it's unlocked.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
""",
                        parse_mode="HTML",
                        link_preview_options=LinkPreviewOptions(
                            is_disabled=True
                        )
                    )

                elif update.callback_query:
                    await update.callback_query.answer(
                        "🔒 Bot is locked. Try again later.",
                        show_alert=True
                    )

                return

        return await super().process_update(
            update,
            *args,
            **kwargs
        )


def create_application() -> Application:
    """Create and configure the bot application."""

    try:
        logger.info("Creating application...")

        request = HTTPXRequest(
            read_timeout=120,
            write_timeout=120,
            connect_timeout=60,
        )

        app = (
            LockedApplication.builder()
            .token(BOT_TOKEN)
            .request(request)
            .post_init(startup)
            .post_shutdown(shutdown)
            .build()
        )

        if app is None:
            raise RuntimeError(
                "Application builder returned None"
            )

        logger.info("Application built successfully")

        register_handlers(app)
        register_gates(app)

        app.add_error_handler(global_error_handler)

        logger.info(
            "Handlers, gates, and error handler registered"
        )

        return app

    except Exception as e:
        logger.exception(
            f"Failed to create application: {e}"
        )
        raise


async def delete_webhook(app: Application):
    """Delete any active webhook to prevent polling conflicts."""
    try:
        logger.info("Deleting active webhook if any...")
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted successfully.")
    except Exception as e:
        logger.warning(f"Failed to delete webhook: {e}")


def main():
    """Start the bot."""

    print("🔴 main() called")
    print_banner()
    print("🟡 Creating application...")

    try:
        app = create_application()

    except Exception as e:
        logger.critical(
            f"Fatal error during application creation: {e}"
        )
        sys.exit(1)

    if app is None:
        logger.critical(
            "Application is None after creation. Exiting."
        )
        sys.exit(1)

    print("🟢 Application created")
    
    try:
        asyncio.run(delete_webhook(app))
    except Exception as e:
        logger.warning(f"Could not run delete_webhook loop: {e}")

    logger.info("Starting polling...")

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=None
    )

    print("🔵 Polling ended")


if __name__ == "__main__":

    try:
        import fcntl

        LOCK_FILE = "/tmp/bot.lock"
        lock_fd = open(LOCK_FILE, "w")

        fcntl.flock(
            lock_fd,
            fcntl.LOCK_EX | fcntl.LOCK_NB
        )

        lock_fd.write(str(os.getpid()))
        lock_fd.flush()

    except (IOError, BlockingIOError, ImportError):
        pass

    print("🟣 __main__ block entered")

    try:
        main()

    except KeyboardInterrupt:
        logger.warning(
            "Bot stopped by keyboard."
        )

    except Exception as e:
        logger.exception(
            f"Fatal startup error: {e}"
        )

    finally:
        try:
            fcntl.flock(
                lock_fd,
                fcntl.LOCK_UN
            )
            lock_fd.close()
            os.remove(LOCK_FILE)

        except:
            pass
