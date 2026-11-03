
from telegram import Update, LinkPreviewOptions
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime, timedelta
from config import OWNER_USERNAME, OWNER_NAME, BOT_USERNAME

from logger import get_logger
from database.db import (
    get_key,
    can_redeem,
    already_redeemed,
    add_redeem,
    increase_redeem,
    extend_premium,
    get_premium_until,
    is_premium,
    user_exists,
    add_user,
)
from ui.emojis import PremiumEmoji as E
from ui.fonts import mono
from utils.decorators import not_banned, log_command
from utils.lock_check import check_lock

logger = get_logger(__name__)


@check_lock
@not_banned
@log_command
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        logger.warning("Redeem called without effective user or message; ignoring.")
        return

    if context.args and context.args[0].startswith("redeem_"):
        key = context.args[0].replace("redeem_", "", 1)
        context.args = [key]

    if len(context.args) != 1:
        await message.reply_text(
            f"""
{E.INFO} ⌠ 𝙍𝙀𝘿𝙀𝙀𝙈 𝙆𝙀𝙔 ⌡
━━━━━━━━━━━━━━━━━━
<b>Usage:</b>
<code>/redeem &lt;key&gt;</code>

<b>Example:</b>
<code>/redeem OGGY-PROO-XXXX-XXXX</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    key = context.args[0].strip().upper()

    if is_premium(user.id):
        await message.reply_text(
            f"""
{E.WARNING} ⌠ 𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} You already have an active Premium subscription.

Wait until it expires before redeeming another key.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    data = get_key(key)
    if not data:
        await message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙄𝙉𝙑𝘼𝙇𝙄𝘿 𝙆𝙀𝙔 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} The key you entered is invalid or has expired.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if hasattr(data, 'keys'):
        data = dict(data)

    if data.get("expires_at"):
        expires_at = datetime.fromisoformat(data["expires_at"])
        if expires_at < datetime.now():
            await message.reply_text(
                f"""
{E.ERROR} ⌠ 𝙆𝙀𝙔 𝙀𝙓𝙋𝙄𝙍𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} This key has expired.

Keys expire 6 hours after creation.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
            return

    if not can_redeem(key):
        await message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙇𝙄𝙈𝙄𝙏 𝙍𝙀𝘼𝘾𝙃𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} This key has reached its redeem limit.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if already_redeemed(key, user.id):
        await message.reply_text(
            f"""
{E.WARNING} ⌠ 𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝙍𝙀𝘿𝙀𝙀𝙈𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} You have already redeemed this key.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    days = data["days"]
    
    if not user_exists(user.id):
        add_user(user.id, user.first_name, user.username)
    
    success = extend_premium(user.id, days)
    
    if not success:
        await message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙍𝙀𝘿𝙀𝙀𝙈 𝙁𝘼𝙄𝙇𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Failed to activate premium. Please contact support.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    
    add_redeem(key, user.id)
    increase_redeem(key)

    expires = get_premium_until(user.id)

    logger.info(f"Key redeemed | User={user.id} | Key={key}")

    if expires:
        expiry_str = expires.strftime('%d %b %Y %H:%M')
    else:
        expiry_str = (datetime.now() + timedelta(days=days)).strftime('%d %b %Y %H:%M')

    await message.reply_text(
        f"""
{E.SUCCESS} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝘼𝘾𝙏𝙄𝙑𝘼𝙏𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.USER} <b>User</b> ↬ {user.full_name}
{E.KEY} <b>Key</b> ↬ <code>{key}</code>
{E.CLOCK} <b>Duration</b> ↬ <code>{days} Days</code>
{E.CALANDER} <b>Expires</b> ↬ <code>{expiry_str}</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


async def handle_redeem_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start redeem_<key> command."""
    if context.args and context.args[0].startswith("redeem_"):
        await redeem(update, context)


def register_redeem(app: Application):
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("start", handle_redeem_start))
    logger.info("✅ Redeem handler registered.")
