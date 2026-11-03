

from telegram import Update, LinkPreviewOptions
from telegram.ext import CommandHandler, ContextTypes
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from database.db import is_bot_locked, set_bot_lock
from utils.decorators import owner_only, log_command
from logger import get_logger
from ui.emojis import PremiumEmoji as E

logger = get_logger(__name__)


@owner_only
@log_command
async def lock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if is_bot_locked():
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝘽𝙊𝙏 𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} Bot is currently in lock mode.

Use /unlock to unlock the bot.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    set_bot_lock(True)
    logger.info(f"Bot locked by {user.id}")

    await update.message.reply_text(
        f"""
{E.SUCCESS} ⌠ 𝘽𝙊𝙏 𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.LOCK} Bot is now in maintenance mode.

All commands are temporarily disabled.

Use /unlock to restore normal operation.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


@owner_only
@log_command
async def unlock_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_bot_locked():
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝘽𝙊𝙏 𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝙐𝙉𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} Bot is already in normal operation mode.

Use /lock to lock the bot if needed.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    set_bot_lock(False)
    logger.info(f"Bot unlocked by {user.id}")

    await update.message.reply_text(
        f"""
{E.SUCCESS} ⌠ 𝘽𝙊𝙏 𝙐𝙉𝙇𝙊𝘾𝙆𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.FLY} Bot is now back to normal operation.

All commands are now available.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


def register_lock_commands(app):
    app.add_handler(CommandHandler("lock", lock_bot))
    app.add_handler(CommandHandler("unlock", unlock_bot))
    logger.info("Lock commands registered.")