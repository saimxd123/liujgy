

import aiohttp
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime
from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes, CommandHandler
from logger import get_logger
from typing import Optional
from ui.emojis import PremiumEmoji as E

logger = get_logger(__name__)

BINLIST_URL = "https://bins.antipublic.cc/bins/{}"
REQUEST_TIMEOUT = 10
MAX_RETRIES = 2





BIN_CACHE = {}
CACHE_FILE = Path("data/bin_cache.json")

def load_bin_cache():
    """Load BIN cache from file."""
    global BIN_CACHE
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                BIN_CACHE = json.load(f)
            logger.info(f"Loaded {len(BIN_CACHE)} BINs from cache")
        else:
            logger.info("No BIN cache file found, starting fresh")
    except Exception as e:
        logger.error(f"Failed to load BIN cache: {e}")
        BIN_CACHE = {}

def save_bin_cache():
    """Save BIN cache to file."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(BIN_CACHE, f, indent=2)
        logger.info(f"Saved {len(BIN_CACHE)} BINs to cache")
    except Exception as e:
        logger.error(f"Failed to save BIN cache: {e}")





async def get_bin_info(bin_number: str) -> dict:
    """
    Fetch BIN information - check cache first, then API.
    """
    if not bin_number or not bin_number.isdigit():
        return {
            "bin": bin_number[:6] if bin_number else "Unknown",
            "scheme": "Unknown",
            "type": "Unknown",
            "level": "Unknown",
            "brand": "Unknown",
            "bank": "Unknown",
            "country": "Unknown",
            "country_code": "Unknown",
            "country_emoji": "🌍",
            "currency": "USD",
            "country_currencies": ["USD"],
            "country_flag": "🌍",
            "country_name": "Unknown",
            "prepaid": False,
            "commercial": False,
        }

    bin_number = bin_number[:6]
    

    if bin_number in BIN_CACHE:
        logger.debug(f"✅ BIN {bin_number} found in cache")
        return BIN_CACHE[bin_number]


    logger.info(f"🔄 BIN {bin_number} not in cache, fetching from API...")
    
    for attempt in range(MAX_RETRIES):
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(BINLIST_URL.format(bin_number)) as resp:
                    if resp.status == 429:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(2)
                            continue
                        result = _create_unknown_bin(bin_number)
                        BIN_CACHE[bin_number] = result
                        save_bin_cache()
                        return result
                        
                    if resp.status == 404:
                        result = _create_unknown_bin(bin_number)
                        BIN_CACHE[bin_number] = result
                        save_bin_cache()
                        return result
                        
                    if resp.status != 200:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(1)
                            continue
                        result = _create_unknown_bin(bin_number)
                        BIN_CACHE[bin_number] = result
                        save_bin_cache()
                        return result

                    data = await resp.json()
                    
                    currencies = data.get("country_currencies", [])
                    currency = currencies[0] if currencies else "USD"
                    
                    result = {
                        "bin": data.get("bin", bin_number),
                        "scheme": data.get("brand", "Unknown"),
                        "type": data.get("type", "Unknown"),
                        "level": data.get("level", "Unknown"),
                        "brand": data.get("brand", "Unknown"),
                        "bank": data.get("bank", "Unknown"),
                        "country": data.get("country_name", "Unknown"),
                        "country_code": data.get("country", "Unknown"),
                        "country_emoji": data.get("country_flag", "🌍"),
                        "country_flag": data.get("country_flag", "🌍"),
                        "country_name": data.get("country_name", "Unknown"),
                        "currency": currency,
                        "country_currencies": currencies,
                        "prepaid": data.get("prepaid", False),
                        "commercial": data.get("commercial", False),
                    }
                    

                    BIN_CACHE[bin_number] = result
                    save_bin_cache()
                    
                    logger.info(f"✅ BIN {bin_number} fetched from API and cached")
                    return result
                    
        except asyncio.TimeoutError:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(1)
                continue
            logger.error(f"BIN fetch timeout for {bin_number}")
            result = _create_unknown_bin(bin_number)
            BIN_CACHE[bin_number] = result
            save_bin_cache()
            return result
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(1)
                continue
            logger.error(f"BIN fetch error for {bin_number}: {e}")
            result = _create_unknown_bin(bin_number)
            BIN_CACHE[bin_number] = result
            save_bin_cache()
            return result
    

    result = _create_unknown_bin(bin_number)
    BIN_CACHE[bin_number] = result
    save_bin_cache()
    return result

def _create_unknown_bin(bin_number: str) -> dict:
    """Create unknown BIN result."""
    return {
        "bin": bin_number,
        "scheme": "Unknown",
        "type": "Unknown",
        "level": "Unknown",
        "brand": "Unknown",
        "bank": "Unknown",
        "country": "Unknown",
        "country_code": "Unknown",
        "country_emoji": "🌍",
        "country_flag": "🌍",
        "country_name": "Unknown",
        "currency": "USD",
        "country_currencies": ["USD"],
        "prepaid": False,
        "commercial": False,
    }





def get_bin_info_sync(bin_number: str) -> dict:
    """Sync version - uses cache only, no API call."""
    if not bin_number or not bin_number.isdigit() or len(bin_number) < 6:
        return _create_unknown_bin(bin_number[:6] if bin_number else "Unknown")
    bin_number = bin_number[:6]
    if bin_number in BIN_CACHE:
        return BIN_CACHE[bin_number]
    return _create_unknown_bin(bin_number)





def extract_cards_from_text(text: str) -> list:
    """Extract card numbers from text (supports various formats)."""
    if not text:
        return []
    

    pattern1 = r'\b(\d{13,19})\b'
    

    pattern2 = r'(\d{13,19})\s*[|/:]\s*(\d{1,2})\s*[|/:]\s*(\d{2,4})\s*[|/:]\s*(\d{3,4})'
    

    pattern3 = r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})'
    
    cards = []
    

    matches = re.findall(pattern2, text)
    for match in matches:
        card_number = match[0]
        cards.append(card_number)
    

    if not cards:
        matches = re.findall(pattern3, text)
        for match in matches:
            card_number = match[0]
            cards.append(card_number)
    

    if not cards:
        matches = re.findall(pattern1, text)
        for match in matches:

            if len(match) >= 13 and len(match) <= 19:
                cards.append(match)
    

    seen = set()
    unique = []
    for card in cards:
        if card not in seen:
            seen.add(card)
            unique.append(card)
    
    return unique

def extract_card_from_text(text: str) -> Optional[str]:
    """Extract first valid card number from text."""
    cards = extract_cards_from_text(text)
    return cards[0] if cards else None





def format_bin_response(bin_info: dict, user_id: int, first_name: str) -> str:
    """Format BIN info with new UI style."""
    bin_num = bin_info.get('bin', 'Unknown')
    brand = bin_info.get('brand', 'Unknown')
    scheme = bin_info.get('scheme', 'Unknown')
    level = bin_info.get('level', 'Unknown')
    card_type = bin_info.get('type', 'Unknown')
    bank = bin_info.get('bank', 'Unknown')
    country = bin_info.get('country', 'Unknown')
    country_emoji = bin_info.get('country_flag', '🌍')
    currency = bin_info.get('currency', 'USD')
    

    brand_parts = [brand]
    if level and level != 'Unknown':
        brand_parts.append(level)
    if card_type and card_type != 'Unknown':
        brand_parts.append(card_type)
    brand_display = ' '.join(brand_parts)
    
    return f"""
{E.APPROVE} ⌠ 𝘽𝙄𝙉 𝙄𝙉𝙁𝙊 ⌡
━━━━━━━━━━━━━━━━━━
<b>BIN</b> ➜ <code>{bin_num}</code>
<b>Brand</b> ➜ <code>{brand_display}</code>
<b>Level</b> ➜ <code>{level}</code>
<b>Bank</b> ➜ <code>{bank}</code>
<b>Country</b> ➜ <code>{country_emoji} {country}</code>
<b>Type</b> ➜ <code>{card_type}</code>
<b>Currency</b> ➜ <code>{currency}</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➜ <a href="https://t.me/oggyproo"><code>𝑶𝑮𝑮𝒀</code></a>
"""



async def handle_bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bin command - lookup BIN information."""
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name
    
    card_text = None
    

    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        

        text = replied.text or replied.caption or ""
        

        card_text = extract_card_from_text(text)
        

        if card_text:
            logger.info(f"Extracted card from reply: {card_text[:6]}...")
        else:
            logger.debug("No card found in replied message")
    

    if not card_text and context.args:
        card_text = context.args[0]
    

    if not card_text and update.message.text:
        card_text = extract_card_from_text(update.message.text)
    

    if not card_text and update.message.text:
        card_text = extract_card_from_text(update.message.text)
    
    if not card_text:
        await update.message.reply_text(
            f"""
[∆] BIN Lookup 
────────────
Usage:
/bin 424242
/bin 4242424242424242

Or reply to a message with a card:
/bin (reply to any message with card)

────────────
[×] Dev ➠ <a href='https://t.me/oggyproo'>𝑶𝑮𝑮𝒀</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    

    card_text = card_text.replace(" ", "").replace("-", "")
    

    bin_number = card_text[:6]
    if not bin_number.isdigit() or len(bin_number) < 6:
        await update.message.reply_text(
            f"""
[∆] BIN Lookup 
────────────
❌ Invalid BIN

Please provide a valid card number or BIN (6+ digits).

Found: <code>{card_text}</code>
────────────
[×] Dev ➠ <a href='https://t.me/oggyproo'>𝑶𝑮𝑮𝒀</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    

    progress = await update.message.reply_text(
        f"""
[∆] BIN Lookup 
────────────
🔍 Looking up BIN: <code>{bin_number}</code>
⏳ Checking cache & API...
────────────
[×] Dev ➠ <a href='https://t.me/oggyproo'>𝑶𝑮𝑮𝒀</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    
    try:

        bin_info = await get_bin_info(bin_number)
        

        formatted = format_bin_response(bin_info, user_id, first_name)
        
        await progress.edit_text(
            formatted,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        
    except Exception as e:
        logger.error(f"BIN lookup error: {e}")
        await progress.edit_text(
            f"""
[∆] BIN Lookup 
────────────
❌ Error: {str(e)[:100]}
────────────
[×] Dev ➠ <a href='https://t.me/oggyproo'>𝑶𝑮𝑮𝒀</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )





def register_bin(app):
    """Register BIN command."""
    app.add_handler(CommandHandler("bin", handle_bin_command))
    logger.info("✅ /bin registered (BIN Lookup)")





load_bin_cache()