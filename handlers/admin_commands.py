

from telegram import Update, LinkPreviewOptions
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime, timedelta

from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from database.db import (
    get_user,
    is_admin,
    is_premium,
    is_banned,
    ban_user,
    unban_user,
    add_admin,
    remove_admin,
    set_premium,
    remove_premium,
)
from utils.decorators import admin_only, owner_only, log_command
from utils.lock_check import check_lock
from utils.html_utils import sanitize_html
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from core.callbacks import Callback

logger = get_logger(__name__)


@check_lock
@admin_only
@log_command
async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if len(context.args) != 2:
        text = f"""
{E.INFO} ⌠ 𝘼𝙐𝙏𝙃 𝙐𝙎𝙀𝙍 ⌡
━━━━━━━━━━━━━━━━━━
<b>Usage:</b>
<code>/auth user_id days</code>

<b>Examples:</b>
<code>/auth 123456789 30</code>  → 30 days premium
<code>/auth 123456789 7</code>   → 7 days premium
━━━━━━━━━━━━━━━━━━
<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
    except ValueError:
        text = f"""
{E.ERROR} ⌠ 𝙄𝙉𝙑𝘼𝙇𝙄𝘿 𝙄𝙉𝙋𝙐𝙏 ⌡
━━━━━━━━━━━━━━━━━━
User ID and days must be numbers.
━━━━━━━━━━━━━━━━━━
<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if days <= 0:
        text = f"""
{E.ERROR} ⌠ 𝙄𝙉𝙑𝘼𝙇𝙄𝘿 𝘿𝘼𝙔𝙎 ⌡
━━━━━━━━━━━━━━━━━━
Days must be greater than 0.
━━━━━━━━━━━━━━━━━━
<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target = get_user(target_id)
    if not target:
        text = f"""
{E.ERROR} ⌠ 𝙐𝙎𝙀𝙍 𝙉𝙊𝙏 𝙁𝙊𝙐𝙉𝘿 ⌡
━━━━━━━━━━━━━━━━━━
User <code>{target_id}</code> not found.
━━━━━━━━━━━━━━━━━━
<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    target_dict = dict(target)

    if is_premium(target_id):
        text = f"""
{E.WARNING} ⌠ 𝘼𝙇𝙍𝙀𝘼𝘿𝙔 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 ⌡
━━━━━━━━━━━━━━━━━━
User <code>{target_id}</code> already has premium.
━━━━━━━━━━━━━━━━━━
<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    expires = datetime.now() + timedelta(days=days)
    set_premium(target_id, expires)

    from handlers.premium_notify import schedule_premium_notifications
    schedule_premium_notifications(context.bot, target_id, expires)


    try:
        from handlers.premium_notify import send_premium_activation_message
        await send_premium_activation_message(context.bot, target_id, expires)
    except Exception as e:
        logger.error(f"Failed to send premium activation message: {e}")

    text = f"""
{E.SUCCESS} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙂𝙄𝙑𝙀𝙉 ⌡
━━━━━━━━━━━━━━━━━━
<b>User</b> ↬ <code>{target_id}</code>
<b>Name</b> ↬ {target_dict.get('first_name', 'Unknown')}
<b>Duration</b> ↬ <code>{days} days</code>
<b>Expires</b> ↬ <code>{expires.strftime('%d %b %Y %H:%M')}</code>

{E.SUCCESS} Activation message sent to user.
━━━━━━━━━━━━━━━━━━
<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    text = sanitize_html(text)
    
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    logger.info(f"User {target_id} given {days} days premium by {user.id}")


@check_lock
@admin_only
@log_command
async def unauth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if len(context.args) != 1:
        text = f"""
{E.INFO} <b>Usage:</b>
<code>/unauth user_id</code>

<b>Example:</b>
<code>/unauth 123456789</code>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            f"{E.ERROR} Invalid user ID.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target = get_user(target_id)
    if not target:
        text = f"{E.ERROR} User <code>{target_id}</code> not found."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    target_dict = dict(target)

    if not is_premium(target_id):
        text = f"{E.WARNING} User <code>{target_id}</code> doesn't have premium."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    remove_premium(target_id)
    try:
        from handlers.premium_notify import cancel_premium_notifications, send_premium_expired_message
        cancel_premium_notifications(target_id)
        await send_premium_expired_message(context.bot, target_id, force=True)
    except Exception as e:
        logger.error(f"Failed to handle premium revocation notification: {e}")

    text = f"""
{E.SUCCESS} <b>Premium Removed!</b>

<b>User</b> ↬ <code>{target_id}</code>
<b>Name</b> ↬ {target_dict.get('first_name', 'Unknown')}

<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    text = sanitize_html(text)

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    logger.info(f"Premium removed from {target_id} by {user.id}")


@owner_only
@log_command
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if len(context.args) != 1:
        text = f"""
{E.INFO} <b>Usage:</b>
<code>/addadmin user_id</code>

<b>Example:</b>
<code>/addadmin 123456789</code>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            f"{E.ERROR} Invalid user ID.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target = get_user(target_id)
    if not target:
        text = f"{E.ERROR} User <code>{target_id}</code> not found."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target_dict = dict(target)

    if is_admin(target_id):
        text = f"{E.WARNING} User <code>{target_id}</code> is already an admin."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    add_admin(target_id, user.id)

    text = f"""
{E.SUCCESS} <b>Admin Added!</b>

<b>User</b> ↬ <code>{target_id}</code>
<b>Name</b> ↬ {target_dict.get('first_name', 'Unknown')}

<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    text = sanitize_html(text)

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    logger.info(f"User {target_id} added as admin by {user.id}")


@owner_only
@log_command
async def rmadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if len(context.args) != 1:
        text = f"""
{E.INFO} <b>Usage:</b>
<code>/rmadmin user_id</code>

<b>Example:</b>
<code>/rmadmin 123456789</code>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            f"{E.ERROR} Invalid user ID.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target = get_user(target_id)
    if not target:
        text = f"{E.ERROR} User <code>{target_id}</code> not found."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target_dict = dict(target)

    if target_id == OWNER_ID:
        text = f"{E.WARNING} Can't remove the owner from admin."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if not is_admin(target_id):
        text = f"{E.WARNING} User <code>{target_id}</code> is not an admin."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    remove_admin(target_id)

    text = f"""
{E.SUCCESS} <b>Admin Removed!</b>

<b>User</b> ↬ <code>{target_id}</code>
<b>Name</b> ↬ {target_dict.get('first_name', 'Unknown')}

<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    text = sanitize_html(text)

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    logger.info(f"User {target_id} removed from admin by {user.id}")


@check_lock
@admin_only
@log_command
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if len(context.args) != 1:
        text = f"{E.INFO} Usage:\n<code>/ban user_id</code>"
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            f"{E.ERROR} Invalid user ID.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target = get_user(target_id)
    if not target:
        await update.message.reply_text(
            f"{E.ERROR} User not found.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if target_id == OWNER_ID:
        await update.message.reply_text(
            f"{E.WARNING} Can't ban the owner.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if is_admin(target_id) and user.id != OWNER_ID:
        await update.message.reply_text(
            f"{E.WARNING} You can't ban another admin. Only owner can.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if is_banned(target_id):
        await update.message.reply_text(
            f"{E.WARNING} User is already banned.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    ban_user(target_id)
    await update.message.reply_text(
        f"{E.SUCCESS} User banned!",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    
    logger.info(f"User {target_id} banned by {user.id}")


@check_lock
@admin_only
@log_command
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if len(context.args) != 1:
        text = f"""
{E.INFO} <b>Usage:</b>
<code>/unban user_id</code>

<b>Example:</b>
<code>/unban 123456789</code>"""
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            f"{E.ERROR} Invalid user ID.",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target = get_user(target_id)
    if not target:
        text = f"{E.ERROR} User <code>{target_id}</code> not found."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    target_dict = dict(target)

    if not is_banned(target_id):
        text = f"{E.WARNING} User <code>{target_id}</code> is not banned."
        text = sanitize_html(text)
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    unban_user(target_id)

    text = f"""
{E.SUCCESS} <b>User Unbanned!</b>

<b>User</b> ↬ <code>{target_id}</code>
<b>Name</b> ↬ {target_dict.get('first_name', 'Unknown')}

<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    text = sanitize_html(text)

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    logger.info(f"User {target_id} unbanned by {user.id}")


def register_admin_commands(app: Application):
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("unauth", unauth))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("rmadmin", rmadmin))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    logger.info("Admin commands registered.")