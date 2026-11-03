

from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

from config import START_PHOTO, OWNER_USERNAME, OWNER_NAME
from logger import get_logger
from database.db import get_user, is_premium, is_banned, is_admin
from ui.buttons import profile_buttons, back_close_buttons
from ui.emojis import PremiumEmoji as E
from ui.emojis import ButtonEmoji as BE
from core.callbacks import Callback
from utils.lock_check import check_lock
from utils.html_utils import sanitize_html

logger = get_logger(__name__)

@check_lock
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = get_user(user.id)

    if not data:
        await update.message.reply_text(
            "User not found.\nUse /start first.",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    if hasattr(data, 'keys'):
        data = dict(data)

    premium = f"{E.SUCCESS} Yes" if is_premium(user.id) else f"{E.ERROR} No"
    
    premium_until = data.get("premium_until")
    if premium_until:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(premium_until)
            expiry_display = dt.strftime("%d %b %Y")
        except:
            expiry_display = premium_until
    else:
        expiry_display = "Never"
    
    banned = f"{E.SUCCESS} Yes" if is_banned(user.id) else f"{E.ERROR} No"
    admin = f"{E.SUCCESS} Yes" if is_admin(user.id) else f"{E.ERROR} No"

    joined_at = data.get("joined_at")
    if joined_at:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(joined_at.replace(" ", "T"))
            joined_display = dt.strftime("%d %b %Y")
        except:
            joined_display = joined_at
    else:
        joined_display = "Unknown"


    text = f"""
{E.SEARCH} ⌠ 𝙿𝚁𝙾𝙵𝙸𝙻𝙴 ⌡
━━━━━━━━━━━━━━━━━━
{E.EMOJI_2} <b>Name</b>     : {data.get('first_name', 'Unknown')}
{E.EMOJI_4} <b>ID</b>       : <code>{data.get('user_id', user.id)}</code>
{E.EMOJI_4} <b>Username</b> : @{data.get('username') or 'None'}

{E.EMOJI_6} <b>Premium</b>  : {premium}
{E.CALANDER} <b>Expires</b>   : {expiry_display}

{E.EMOJI_8} <b>Joined</b>   : {joined_display}
━━━━━━━━━━━━━━━━━━
<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    

    text = sanitize_html(text)

    try:

        await update.message.reply_photo(
            photo=START_PHOTO,
            caption=text,
            parse_mode="HTML",
            reply_markup=profile_buttons()
        )
    except Exception as e:
        logger.error(f"Profile photo error: {e}")

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=profile_buttons(),
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

    logger.info(f"/id -> {user.id}")



def _format_info(user_data, user_id, live_user=None):
    data = dict(user_data) if hasattr(user_data, "keys") else user_data
    username = live_user.username if live_user is not None else data.get("username")
    first_name = live_user.first_name if live_user is not None else data.get("first_name")
    premium = is_premium(user_id)
    premium_until = data.get("premium_until")
    if premium_until:
        try:
            premium_until = datetime.fromisoformat(str(premium_until).replace("Z", "+00:00"))
            premium_display = premium_until.strftime("%d %b %Y, %H:%M")
        except Exception:
            premium_display = str(premium_until)
    else:
        premium_display = "N/A"
    joined = data.get("joined_at")
    if joined:
        try:
            joined = datetime.fromisoformat(str(joined).replace("Z", "+00:00")).strftime("%d %b %Y")
        except Exception:
            joined = str(joined)
    else:
        joined = "N/A"
    role = "Owner" if user_id == OWNER_ID else "Admin" if is_admin(user_id) else "User"
    status = "Banned" if is_banned(user_id) else "Active"
    plan = "Premium" if premium else "Free"
    credits = get_user_credits(user_id)
    return (
        "<b>Aᴄᴄᴏᴜɴᴛ Iɴғᴏʀᴍᴀᴛɪᴏɴ ✅</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"Usᴇʀ ➺ {first_name or 'Unknown'}\n"
        f"Usᴇʀɴᴀᴍᴇ ➺ @{username or 'None'}\n"
        f"Usᴇʀ ID ➺ <code>{user_id}</code>\n"
        f"Pʟᴀɴ ➺ {plan}\n"
        f"Cʀᴇᴅɪᴛs ➺ {credits}\n"
        f"Rᴏʟᴇ ➺ {role}\n"
        f"Sᴛᴀᴛᴜs ➺ {status}\n"
        f"Pʀᴇᴍɪᴜᴍ Uɴᴛɪʟ ➺ {premium_display}\n"
        f"Jᴏɪɴᴇᴅ ➺ {joined}"
    )


@check_lock
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requester = update.effective_user
    target_id = requester.id
    live_user = requester

    if context.args:
        if requester.id != OWNER_ID and not is_admin(requester.id):
            await update.message.reply_text("❌ Only admins can look up another user.")
            return
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ User ID must be a number.")
            return
        live_user = None

    data = get_user(target_id)
    if not data:
        await update.message.reply_text("❌ This user is not in the bot database.")
        return

    if target_id == requester.id:
        update_user_identity(target_id, requester.first_name or "User", requester.username)
        data = get_user(target_id)
        live_user = requester

    text = sanitize_html(_format_info(data, target_id, live_user))
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def register_profile(app: Application):
    app.add_handler(CommandHandler("id", profile))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("info", info))
    logger.info("Profile handlers registered.")