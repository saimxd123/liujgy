

import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import BadRequest
from config import OWNER_ID, START_PHOTO, OWNER_USERNAME, OWNER_NAME

from ui.buttons import (
    home_buttons,
    profile_buttons,
    admin_panel_buttons,
    pricing_buttons,
    back_close_buttons,
)
from ui.emojis import PremiumEmoji as E
from ui.emojis import ButtonEmoji as BE

from database.db import (
    get_user,
    is_premium,
    is_admin,
    is_banned,
    get_user_proxies,
    get_total_sites,
    get_total_users,
    get_total_admins,
    get_total_premium,
    get_total_banned,
    get_total_proxies,
)
from core.callbacks import Callback
from logger import get_logger
from utils.html_utils import sanitize_html

logger = get_logger(__name__)

BULLET = "▸"


def get_commands_pages(user_id: int) -> dict:
    """Build the command documentation visible to the current user.

    Visibility rules:
      - Regular users: public/user commands only.
      - Admins: public commands + admin commands.
      - Owner: public commands + admin commands + owner-only commands.
    """
    is_user_owner = user_id == OWNER_ID
    is_user_admin = is_user_owner or is_admin(user_id)
    is_user_premium = is_premium(user_id)

    page1 = f"""
{E.SEARCH} ⌠ 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎 ⌡ 1/2
━━━━━━━━━━━━━━━━━━

▸ {E.USER} <b>𝙐𝙨𝙚𝙧</b>
/start - Start the bot
/cmds - Open command menu
/id /profile /info - View your account info
/me - Your stats

━━━━━━━━━━━━━━━━━━
▸ {E.GATES} <b>𝙂𝙖𝙩𝙚𝙨</b>
/sh - Shopify
/msh - Mass Shopify {E.STAR if is_user_premium else E.LOCK}
/chk - Stripe Auth
/mchk - Stripe Auth Mass {E.STAR if is_user_premium else E.LOCK}
/auth - Stripe Auth2 $0 (WooCommerce)
/mauth - Mass Auth2 $0 {E.STAR if is_user_premium else E.LOCK}
/st - Stripe Charge $5 (GiveWP)
/mst - Mass Charge $5 {E.STAR if is_user_premium else E.LOCK}

━━━━━━━━━━━━━━━━━━
▸ {E.HAMMER if hasattr(E, 'HAMMER') else E.TOOLS} <b>𝙃𝙞𝙩𝙩𝙚𝙧</b>
/hit - Stripe Hitter
/jhit - Jio Hitter (authorized users only)

━━━━━━━━━━━━━━━━━━
▸ {E.TOOLS} <b>𝙏𝙤𝙤𝙡𝙨</b>
/gate - Site scanner
/gen - Card generator
/scr - Scrape cards {E.STAR if is_user_premium else E.LOCK}
/bin - BIN lookup
/fake - Fake identity generator
/fakehelp - Fake generator help

━━━━━━━━━━━━━━━━━━
{E.STAR} <b>Premium</b>: {E.APPROVED if is_user_premium else E.ERROR} {'Active' if is_user_premium else 'Inactive'}
{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    page2 = f"""
{E.SEARCH} ⌠ 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎 ⌡ 2/2
━━━━━━━━━━━━━━━━━━

▸ {E.FILE} <b>𝙏𝙓𝙏 𝘾𝙖𝙧𝙙 𝘾𝙤𝙢𝙢𝙖𝙣𝙙𝙨</b>
/txt - Open menu
/merge - Merge multiple files
/split 500 - Split into chunks (default 1000)
/parts - Show split parts
/clean - Remove duplicates & expired cards
/shuffle - Randomize card order
/done - Finish current file operation
/cancel - Cancel current file operation

━━━━━━━━━━━━━━━━━━
▸ {E.GLOBE} <b>𝙋𝙧𝙤𝙭𝙮</b>
/proxy - Add proxy (reply to text/file)
/tp - Test your proxies
/getproxy - Export proxies as .txt
/rmproxy - Delete proxy by ID
/clearproxy - Clear all your proxies

━━━━━━━━━━━━━━━━━━
▸ {E.REPORT} <b>𝙁𝙚𝙚𝙙𝙗𝙖𝙘𝙠</b>
/fb - Send feedback to admins
"""

    pages = {1: page1}

    if is_user_admin:


        admin_block = f"""
━━━━━━━━━━━━━━━━━━
▸ {E.SHIELD} <b>𝘼𝙙𝙢𝙞𝙣 𝘾𝙤𝙢𝙢𝙖𝙣𝙙𝙨</b>
/admin - Open admin panel
/stats /leaderboard /top - Leaderboard
/bot - Bot statistics
/report - Generate reports
/vps - VPS status
/session - Active sessions
/info <user_id> - Look up a user
"""
        owner_block = f"""
━━━━━━━━━━━━━━━━━━
▸ {E.GEAR} <b>𝙊𝙬𝙣𝙚𝙧 𝘾𝙤𝙢𝙢𝙖𝙣𝙙𝙨</b>
/lock - Lock bot
/unlock - Unlock bot
/speed /mshspeed - Set MSH speed
/broad - Broadcast message
/addadmin - Add admin
/rmadmin - Remove admin
/auth - Give premium
/unauth - Remove premium
/ban - Ban user
/unban - Unban user
/clear all - WIPE EVERYTHING {E.WARNING}
""" if is_user_owner else ""

        page2 = page2.replace(
            f"{E.REPORT} <b>𝙁𝙚𝙚𝙙𝙗𝙖𝙘𝙠</b>\n/fb - Send feedback to admins\n",
            f"{E.REPORT} <b>𝙁𝙚𝙚𝙙𝙗𝙖𝙘𝙠</b>\n/fb - Send feedback to admins\n{admin_block}{owner_block}"
        )

    page2 += f"""

━━━━━━━━━━━━━━━━━━
{E.STAR} <b>Premium</b>: {E.APPROVED if is_user_premium else E.ERROR} {'Active' if is_user_premium else 'Inactive'}
{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    pages[2] = page2
    return pages


def get_command_nav_buttons(page: int, total_pages: int = 2) -> InlineKeyboardMarkup:
    """Get navigation buttons using custom emoji IDs."""
    buttons = []
    
    nav_row = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="Prev",
                callback_data=f"cmd_page:{page-1}",
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"{page}/{total_pages}",
            callback_data="ignore",
            style="primary",
        )
    )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Next",
                callback_data=f"cmd_page:{page+1}",
                style="success",
                icon_custom_emoji_id=BE.VIEW
            )
        )
    buttons.append(nav_row)
    
    buttons.append([
        InlineKeyboardButton(
            text="Home",
            callback_data=Callback.HOME,
            style="primary",
            icon_custom_emoji_id=BE.BACK_EMOJI
        ),
        InlineKeyboardButton(
            text="Close",
            callback_data=Callback.CLOSE,
            style="danger",
            icon_custom_emoji_id=BE.CLOSE_EMOJI
        ),
    ])
    
    return InlineKeyboardMarkup(buttons)


async def render_page(query, text: str, buttons, photo: str = None):
    """Render page with proper HTML sanitization."""
    photo = photo or START_PHOTO
    text = sanitize_html(text)
    try:
        await query.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
        )
    except BadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            return
        if "there is no caption in the message to edit" in error_msg:
            try:
                await query.edit_message_text(
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=buttons,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                return
            except BadRequest as e2:
                if "message is not modified" in str(e2).lower():
                    return
                logger.error(f"Render page text fallback error: {e2}")
                return
        logger.error(f"Render page error: {e}")


async def home_page(query, callback_answered: bool = False):
    """Home page with PremiumEmojis only."""
    user = query.from_user
    is_user_admin = user.id == OWNER_ID or is_admin(user.id)

    text = f"""
{E.CAR} 𝑾𝑬𝑳𝑪𝑶𝑴𝑬 𝑻𝑶 <a href='http://t.me/oggyproo'>𝑶𝑮𝑮𝒀'𝑺 𝑷𝑹𝑰𝑴𝑬 𝑩𝑶𝑻!</a>
━━━━━━━━━━━━━━━━━━
{E.FLY} <a href='http://t.me/oggyproo'>𝑬𝒏𝒋𝒐𝒚 𝒃𝒍𝒂𝒛𝒊𝒏𝒈 𝒔𝒑𝒆𝒆𝒅𝒔</a>
           <a href='http://t.me/oggyproo'>𝒔𝒎𝒂𝒓𝒕 𝒓𝒆𝒕𝒓𝒊𝒆𝒔, 𝑨𝒄𝒄𝒖𝒓𝒂𝒄𝒚</a>
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await render_page(
        query,
        text,
        home_buttons(is_admin=is_user_admin),
    )

    logger.info(f"Home page -> {user.id}")


async def profile_page(query, callback_answered: bool = False):
    """Profile page with PremiumEmojis only."""
    user = query.from_user
    data = get_user(user.id)

    if not data:
        if not callback_answered:
            try:
                await query.answer("❌ User not found.", show_alert=True)
            except Exception:
                pass
        return

    if hasattr(data, 'keys'):
        data = dict(data)

    premium_status = f"{E.APPROVED} Yes" if is_premium(user.id) else f"{E.ERROR} No"
    
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
{E.GRL} <b>𝑷𝒓𝒐𝒇𝒊𝒍𝒆</b>

▸ {E.EMOJI_2} <b>𝐍𝐚𝐦𝐞</b> ➠ {data.get('first_name', 'Unknown')}
▸ {E.EMOJI_3} <b>𝐈𝐃</b> ➠ <code>{data.get('user_id', user.id)}</code>
▸ {E.EMOJI_4} <b>𝐔𝐬𝐞𝐫𝐧𝐚𝐦𝐞</b> ➠ @{data.get('username') or 'None'}

▸ {E.STAR} <b>𝐏𝐫𝐞𝐦𝐢𝐮𝐦</b> ➠ {premium_status} 
▸ {E.CALANDER} <b>𝐄𝐱𝐩𝐢𝐫𝐞𝐬</b> ➠ <code>{expiry_display}</code>

▸ {E.CLOCK} <b>𝐉𝐨𝐢𝐧𝐞𝐝</b> ➠ <code>{joined_display}</code>

{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await render_page(
        query,
        text,
        profile_buttons(),
    )

    logger.info(f"Profile page -> {user.id}")
    

async def commands_page(query, callback_answered: bool = False):
    """Commands page with PremiumEmojis only."""
    user = query.from_user
    user_id = user.id
    
    page = 1
    if query.data and ":" in query.data:
        try:
            page = int(query.data.split(":")[1])
        except (ValueError, IndexError):
            page = 1
    
    pages = get_commands_pages(user_id)
    total_pages = len(pages)
    if page > total_pages:
        page = total_pages
    text = pages.get(page, pages[1])
    reply_markup = get_command_nav_buttons(page, total_pages)
    
    text = sanitize_html(text)
    
    try:
        await query.edit_message_caption(
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            pass
        elif "there is no caption" in error_msg:
            try:
                await query.edit_message_text(
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
            except BadRequest as e2:
                if "message is not modified" not in str(e2).lower():
                    await query.message.reply_text(
                        text=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                        link_preview_options=LinkPreviewOptions(is_disabled=True)
                    )
        else:
            await query.message.reply_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
    except Exception as e:
        logger.error(f"Commands page error: {e}")
        await query.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

    logger.info(f"Commands page {page}/3 -> {user.id}")


async def settings_page(query, callback_answered: bool = False):
    """Settings page with PremiumEmojis only."""
    user = query.from_user

    text = f"""
{E.GEAR} ⌠ 𝙎𝙀𝙏𝙏𝙄𝙉𝙂𝙎 ⌡
━━━━━━━━━━━━━━━━━━
▸ {E.THUNDER} <b>𝐆𝐚𝐭𝐞 𝐒𝐭𝐚𝐭𝐮𝐬</b> ➠ {E.APPROVED} Online
▸ {E.EMOJI_2} <b>𝐏𝐫𝐨𝐟𝐢𝐥𝐞</b> ➠ {user.first_name}
▸ {E.STAR} <b>𝐏𝐫𝐞𝐦𝐢𝐮𝐦</b> ➠ {E.APPROVED if is_premium(user.id) else E.ERROR} {'Active' if is_premium(user.id) else 'Inactive'}

▸ {E.LOCK} <b>𝐀𝐮𝐭𝐡 𝐆𝐚𝐭𝐞𝐬</b> ➠ {E.APPROVED} Online
▸ {E.CARD} <b>𝐂𝐡𝐚𝐫𝐠𝐞 𝐆𝐚𝐭𝐞𝐬</b> ➠ {E.APPROVED} Online
▸ {E.BOX} <b>𝐌𝐚𝐬𝐬 𝐆𝐚𝐭𝐞𝐬</b> ➠ {E.APPROVED} Online

▸ {E.GLOBE} <b>𝐏𝐫𝐨𝐱𝐢𝐞𝐬</b> ➠ <code>{len(get_user_proxies(user.id))}</code>
▸ {E.SITES} <b>𝐆𝐥𝐨𝐛𝐚𝐥 𝐒𝐢𝐭𝐞𝐬</b> ➠ <code>{get_total_sites()}</code>

{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await render_page(
        query,
        text,
        back_close_buttons(Callback.HOME),
    )

    logger.info(f"Settings page -> {user.id}")


async def help_page(query, callback_answered: bool = False):
    """Help page with PremiumEmojis only."""
    text = f"""
{E.HELP} ⌠ 𝙃𝙀𝙇𝙋 𝘾𝙀𝙉𝙏𝙀𝙍 ⌡
━━━━━━━━━━━━━━━━━━
▸ {E.INFO} Need help with the bot?

• /start    → Start the bot
• /id  → View your profile
• /cmds     → List all commands

━━━━━━━━━━━━━━━━━━
▸ <b>For issues or inquiries:</b>

{E.FIRE} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
{E.GRL} <b>Group</b> ➠ <a href='https://t.me/+IFFnzNZuHFU5YmQ0'>Join Group</a>
{E.THUNDER} <b>Updates</b> ➠ <a href='https://t.me/+E6zoRhIFhtNmM2E5'>Join Channel</a>

{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await render_page(
        query,
        text,
        back_close_buttons(Callback.HOME),
    )

    logger.info(f"Help page -> {query.from_user.id}")


async def pricing_page(query, callback_answered: bool = False):
    """Pricing page with PremiumEmojis only."""
    text = f"""
{E.STAR} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙋𝙍𝙄𝘾𝙄𝙉𝙂 ⌡
┏━━━━━━━━━━━━━━━━━━━━━━━
┣ {E.CALANDER} <b>2 Days</b>  ➜ $2.00
┣ {E.CALANDER} <b>7 Days</b>  ➜ $7.00
┣ {E.CALANDER} <b>15 Days</b> ➜ $14.00
┣ {E.CALANDER} <b>30 Days</b> ➜ $25.00

━━━━━━━━━━━━━━━━━━
{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    
    await render_page(
        query,
        text,
        pricing_buttons(),
    )


async def admin_panel(query, callback_answered: bool = False):
    """Admin panel with PremiumEmojis only."""
    user = query.from_user

    if user.id != OWNER_ID and not is_admin(user.id):
        if not callback_answered:
            try:
                await query.answer("❌ Admins only.", show_alert=True)
            except Exception:
                pass
        return

    total_users = get_total_users()
    total_premium = get_total_premium()
    total_admins = get_total_admins()
    total_banned = get_total_banned()
    total_proxies = get_total_proxies()
    total_sites = get_total_sites()

    text = f"""
{E.SHIELD} ⌠ 𝘼𝘿𝙈𝙄𝙉 𝘾𝙊𝙉𝙏𝙍𝙊𝙇 𝙋𝘼𝙉𝙀𝙇 ⌡
━━━━━━━━━━━━━━━━━━
{E.USERS} <b>Users</b>      ↬ <code>{total_users}</code>
{E.STAR} <b>Premium</b>    ↬ <code>{total_premium}</code>
{E.SHIELD} <b>Admins</b>     ↬ <code>{total_admins}</code>
{E.BAN} <b>Banned</b>     ↬ <code>{total_banned}</code>
{E.GLOBE} <b>Proxies</b>    ↬ <code>{total_proxies}</code>
{E.SITES} <b>Sites</b>      ↬ <code>{total_sites}</code>
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await render_page(
        query,
        text,
        admin_panel_buttons(),
    )

    logger.info(f"Admin panel -> {user.id}")






PAGE_HANDLERS = {
    "page_home": home_page,
    "page_profile": profile_page,
    "page_commands": commands_page,
    "page_settings": settings_page,
    "page_help": help_page,
    "page_pricing": pricing_page,
    "page_admin": admin_panel,
}