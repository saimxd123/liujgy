import asyncio
import os
import sys

from telegram import Update, LinkPreviewOptions
from telegram.ext import Application
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, OWNER_ID, OWNER_USERNAME, OWNER_NAME
from logger import get_logger, print_banner
from handlers import register_handlers
from gates import register_gates
from core.errors import global_error_handler
from database.db import init_db, is_bot_locked
from ui.emojis import PremiumEmoji as E

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════
# Startup tasks (run BEFORE polling)
# ═══════════════════════════════════════════════════════════
async def run_startup_tasks(app: Application):
    logger.info("▶️ [STARTUP 1/4] Deleting webhook...")
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ [STARTUP 1/4] Webhook deleted")
    except Exception as e:
        logger.warning(f"⚠️ [STARTUP 1/4] Webhook delete failed: {e}")

    logger.info("▶️ [STARTUP 2/4] Initializing database...")
    try:
        await init_db()
        logger.info("✅ [STARTUP 2/4] Database initialized")
    except Exception as e:
        logger.exception(f"❌ [STARTUP 2/4] Database init failed: {e}")

    logger.info("▶️ [STARTUP 3/4] Verifying bot identity with Telegram...")
    try:
        me = await app.bot.get_me()
        logger.info(f"✅ [STARTUP 3/4] Connected as @{me.username} (id={me.id})")
    except Exception as e:
        logger.exception(f"❌ [STARTUP 3/4] Cannot reach Telegram API: {e}")

    logger.info("▶️ [STARTUP 4/4] Starting premium notification worker...")
    try:
        from handlers.premium_notify import start_premium_notification_worker
        start_premium_notification_worker(app.bot)
        logger.info("✅ [STARTUP 4/4] Premium notification worker started")
    except Exception as e:
        logger.info(f"ℹ️ [STARTUP 4/4] Premium worker skipped: {e}")

    logger.info("🎉 All startup tasks complete")


async def shutdown(app: Application):
    logger.info("𝑶𝑮𝑮𝒀'𝑺 𝑷𝑹𝑰𝑴𝑬 𝑩𝑶𝑻 offline")


# ═══════════════════════════════════════════════════════════
# Lock middleware
# ═══════════════════════════════════════════════════════════
class LockedApplication(Application):
    async def process_update(self, update, *args, **kwargs):
        if update.effective_user:
            uid = update.effective_user.id
            if uid == OWNER_ID:
                return await super().process_update(update, *args, **kwargs)

            if is_bot_locked():
                text = update.message.text if update.message and update.message.text else ""
                if text.startswith(("/lock", "/unlock")):
                    return await super().process_update(update, *args, **kwargs)

                if update.message:
                    try:
                        await update.message.reply_text(
                            f"""
{E.LOCK} ⌠ 𝘽𝙊𝙏 𝙄𝙎 𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
Bot is under maintenance.

Try again later.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
""",
                            parse_mode="HTML",
                            link_preview_options=LinkPreviewOptions(is_disabled=True),
                        )
                    except Exception:
                        pass
                elif update.callback_query:
                    try:
                        await update.callback_query.answer(
                            "🔒 Bot is locked. Try again later.", show_alert=True
                        )
                    except Exception:
                        pass
                return

        return await super().process_update(update, *args, **kwargs)


# ═══════════════════════════════════════════════════════════
# Build
# ═══════════════════════════════════════════════════════════
def create_application() -> Application:
    logger.info("▶️ [CREATE 1/3] Building application...")
    request = HTTPXRequest(read_timeout=120, write_timeout=120, connect_timeout=60)

    app = (
        LockedApplication.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_shutdown(shutdown)
        .build()
    )

    if app is None:
        raise RuntimeError("Application builder returned None")

    logger.info("✅ [CREATE 1/3] Application built")

    register_handlers(app)
    logger.info("✅ [CREATE 2/3] Handlers registered")

    register_gates(app)
    app.add_error_handler(global_error_handler)
    logger.info("✅ [CREATE 3/3] Gates and error handler registered")

    return app


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════
def main():
    print_banner()

    # Ensure a current event loop exists (Python 3.11 requirement)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    logger.info("🔄 Event loop ready")

    try:
        app = create_application()
    except Exception as e:
        logger.critical(f"❌ Fatal during application creation: {e}")
        sys.exit(1)

    logger.info("▶️ Running startup tasks (webhook, DB, identity)...")
    try:
        loop.run_until_complete(run_startup_tasks(app))
    except Exception as e:
        logger.exception(f"❌ Startup tasks crashed: {e}")
        # keep going - polling might still work

    logger.info("🚀 Starting polling...")
    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.exception(f"❌ run_polling failed: {e}")
        raise


if __name__ == "__main__":
    try:
        import fcntl
        LOCK_FILE = "/tmp/bot.lock"
        lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
    except (IOError, BlockingIOError, ImportError):
        pass

    try:
        main()
    except KeyboardInterrupt:
        logger.warning("Bot stopped by keyboard.")
    except Exception as e:
        logger.exception(f"Fatal startup error: {e}")
