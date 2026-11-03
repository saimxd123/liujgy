from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID
from database.db import get_all_users, get_user, is_admin, is_banned, is_premium, get_premium_until, get_total_premium, get_user_credits
from ui.buttons import users_buttons, user_profile_buttons
from utils.pagination import paginate


def _clean(value):
    return str(value).replace("<", "&lt;").replace(">", "&gt;")




async def _edit_user_view(query, text: str, reply_markup):
    """Edit caption or text depending on the current Telegram message."""
    try:
        await query.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        msg = str(exc).lower()
        if "message is not modified" in msg:
            return
        if "there is no caption in the message to edit" in msg:
            await query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            return
        raise


def _user_line(user):
    uid = int(user["user_id"])
    name = user.get("first_name") or user.get("username") or str(uid)
    username = user.get("username")
    premium = is_premium(uid)
    return f"{'⭐' if premium else '🆓'} <b>{_clean(name)}</b> · <code>{uid}</code> · @{_clean(username) if username else 'None'} · {'Premium' if premium else 'Free'}"


async def users_page(query, page: int = 1):
    if query.from_user.id != OWNER_ID and not is_admin(query.from_user.id):
        await query.answer("Admins only.", show_alert=True)
        return
    all_users = get_all_users()
    page_users, page, total_pages = paginate(all_users, page, per_page=8)
    text = (
        f"<b>👥 User Manager</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Total ➺ <code>{len(all_users)}</code>\n"
        f"Live Premium ➺ <code>{get_total_premium()}</code>\n\n"
    )
    text += "\n".join(_user_line(dict(u) if hasattr(u, "keys") else u) for u in page_users) if page_users else "No users found."
    text += f"\n\nPage <code>{page}/{total_pages}</code>\n\n<b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"
    await _edit_user_view(query, text, users_buttons(page, total_pages, [int(u["user_id"]) for u in page_users]))


async def user_profile_page(query, user_id: int):
    if query.from_user.id != OWNER_ID and not is_admin(query.from_user.id):
        await query.answer("Admins only.", show_alert=True)
        return
    user = get_user(user_id)
    if not user:
        await query.answer("User not found.", show_alert=True)
        return
    user = dict(user)
    premium = is_premium(user_id)
    expires = get_premium_until(user_id)
    expiry = expires.strftime("%d %b %Y, %H:%M") if expires else "N/A"
    role = "Owner" if user_id == OWNER_ID else "Admin" if is_admin(user_id) else "User"
    status = "Banned" if is_banned(user_id) else "Active"
    joined = user.get("joined_at") or "N/A"
    text = (
        "<b>Aᴄᴄᴏᴜɴᴛ Iɴғᴏʀᴍᴀᴛɪᴏɴ ✅</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"Usᴇʀ ➺ {_clean(user.get('first_name') or 'Unknown')}\n"
        f"Usᴇʀɴᴀᴍᴇ ➺ @{_clean(user.get('username')) if user.get('username') else 'None'}\n"
        f"Usᴇʀ ID ➺ <code>{user_id}</code>\n"
        f"Pʟᴀɴ ➺ {'Premium' if premium else 'Free'}\n"
        f"Cʀᴇᴅɪᴛs ➺ {get_user_credits(user_id)}\n"
        f"Rᴏʟᴇ ➺ {role}\n"
        f"Sᴛᴀᴛᴜs ➺ {status}\n"
        f"Pʀᴇᴍɪᴜᴍ Uɴᴛɪʟ ➺ {expiry}\n"
        f"Jᴏɪɴᴇᴅ ➺ {_clean(joined)}"
    )
    await _edit_user_view(query, text, user_profile_buttons(user_id=user_id, premium=premium, admin=is_admin(user_id), banned=is_banned(user_id)))
