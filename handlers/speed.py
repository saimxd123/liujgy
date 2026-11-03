

from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes, CommandHandler
from database.db import get_msh_speed, set_msh_speed
from utils.decorators import admin_only, log_command
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID

logger = get_logger(__name__)


@check_lock
@admin_only
@log_command
async def speed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Set or show the MSH (Shopify Mass) speed.
    Usage: /speed [speed]
    - Without argument: shows current MSH speed.
    - With argument: sets MSH speed (1-50).
    """
    user_id = update.effective_user.id


    if not context.args:
        current = get_msh_speed()
        await update.message.reply_text(
            f"""
{E.SITES} <b>MSH (Shopify Mass) Speed</b>
━━━━━━━━━━━━━━━━━━
<b>Current Speed:</b> <code>{current}</code>
━━━━━━━━━━━━━━━━━━
<i>• Lower = Slower but more stable
• Higher = Faster but may cause bans</i>
━━━━━━━━━━━━━━━━━━
<b>To change:</b>
<code>/speed 10</code>  (sets speed to 10)

<i>Running mass checks will NOT be affected
until you start a new one.</i>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='tg://user?id={OWNER_ID}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    try:
        speed = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            f"{E.ERROR} Invalid speed value. Must be a number.", parse_mode="HTML"
        )
        return


    if speed < 1 or speed > 50:
        await update.message.reply_text(
            f"{E.ERROR} Speed must be between 1 and 50.", parse_mode="HTML"
        )
        return


    set_msh_speed(speed)
    current = get_msh_speed()

    await update.message.reply_text(
        f"""
{E.SUCCESS} <b>MSH Speed Updated</b>
━━━━━━━━━━━━━━━━━━
{E.SITES} <b>New MSH Speed:</b> <code>{current}</code> ✅
━━━━━━━━━━━━━━━━━━
<i>Running mass checks will NOT be affected
until you start a new one.</i>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='tg://user?id={OWNER_ID}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    logger.info(f"MSH speed set to {speed} by admin {user_id}")






@check_lock
@admin_only
@log_command
async def msh_speed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /speed (kept for compatibility)."""

    await speed_command(update, context)






def register_speed(app):
    """Register speed handlers."""
    app.add_handler(CommandHandler("speed", speed_command))
    app.add_handler(CommandHandler("mshspeed", msh_speed_command))

    logger.info("✅ Speed (MSH only) handlers registered.")