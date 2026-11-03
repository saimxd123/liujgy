
import secrets
import string
from datetime import datetime, timedelta
from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from logger import get_logger
from database.db import create_key, get_key, set_key_expiry, delete_expired_keys
from ui.emojis import PremiumEmoji as E
from ui.emojis import ButtonEmoji as BE
from utils.decorators import admin_only, log_command
from utils.lock_check import check_lock
from config import OWNER_USERNAME, OWNER_NAME, BOT_USERNAME

logger = get_logger(__name__)

ALPHABET = string.ascii_uppercase + string.digits


def generate_key() -> str:
    parts = []
    for _ in range(4):
        part = "".join(secrets.choice(ALPHABET) for _ in range(4))
        parts.append(part)
    return "OGGY-PROO-" + "-".join(parts[:2])


def get_redeem_link(key: str) -> str:
    """Generate a redeem link for the key."""
    return f"https://t.me/{BOT_USERNAME}?start=redeem_{key}"


def get_redeem_button(key: str) -> InlineKeyboardMarkup:
    """Generate redeem button for the key with style and emoji."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="Redeem Key",
                url=get_redeem_link(key),
                style="success",
                icon_custom_emoji_id=BE.REDEEM
            )
        ]
    ])


@check_lock
@admin_only
@log_command
async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if len(context.args) != 2:
        await update.message.reply_text(
            f"""
{E.INFO} ⌠ 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙀 𝙆𝙀𝙔 ⌡
━━━━━━━━━━━━━━━━━━
<b>Usage:</b>
<code>/genkey &lt;days&gt; &lt;limit&gt;</code>

<b>Example:</b>
<code>/genkey 30 1</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    try:
        days = int(context.args[0])
        limit = int(context.args[1])
    except ValueError:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙄𝙉𝙑𝘼𝙇𝙄𝘿 𝙄𝙉𝙋𝙐𝙏 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Days and limit must be numbers.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if days <= 0 or limit <= 0:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙄𝙉𝙑𝘼𝙇𝙄𝘿 𝙑𝘼𝙇𝙐𝙀 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Days and limit must be greater than 0.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    key = generate_key()

    success = create_key(
        key=key,
        days=days,
        redeem_limit=limit,
        created_by=user.id,
    )

    if not success:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙁𝘼𝙄𝙇𝙀𝘿 𝙏𝙊 𝘾𝙍𝙀𝘼𝙏𝙀 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Failed to create key.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    expires_at = datetime.now() + timedelta(hours=6)
    set_key_expiry(key, expires_at)
    expires_display = expires_at.strftime('%d %b %Y %H:%M')

    redeem_link = get_redeem_link(key)
    copy_command = f"/redeem {key}"

    text = f"""
{E.KEY} ⌠ 𝙆𝙀𝙔 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Key</b> ↬ <code>{key}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Days</b> ↬ <code>{days}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Limit</b> ↬ <code>{limit}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Status</b> ↬ {E.SUCCESS} Ready
<a href='https://t.me/oggyproo'>⊀</a> <b>Expires</b> ↬ <code>{expires_display}</code>

<b>Redeem Link:</b>
<code>{redeem_link}</code>

<b>Command:</b>
<code>{copy_command}</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await update.message.reply_text(
        text=text,
        parse_mode="HTML",
        reply_markup=get_redeem_button(key),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    logger.info(f"Key created -> {key} by {user.id}")


def register_genkey(app: Application):
    app.add_handler(CommandHandler("genkey", genkey))
    logger.info("GenKey handler registered.")
