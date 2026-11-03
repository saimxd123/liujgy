

import re
import os
import asyncio
import logging
import html
import io
import random
import time
from datetime import datetime
from typing import Optional, List, Dict, Set, Tuple
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut, NetworkError

from database.db import get_or_create_user, is_premium
from plans import get_user_current_tier
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID

logger = get_logger(__name__)

try:
    from pyrogram import Client as PyrogramClient
    from pyrogram.errors import (
        UserAlreadyParticipant,
        InviteHashExpired,
        InviteHashInvalid,
        InviteRequestSent,
        InviteHashEmpty,
        ChannelInvalid,
        ChannelPrivate,
        UsernameNotOccupied,
        FloodWait,
        PeerIdInvalid,
        UserNotParticipant,
        ChatWriteForbidden,
        ChatAdminRequired,
    )
    PYROGRAM_AVAILABLE = True
    logger.info("✅ Pyrogram available")
except ImportError as e:
    logger.warning(f"Pyrogram not available: {e}")
    PYROGRAM_AVAILABLE = False

from config import API_ID, API_HASH, SESSION_STRING





CARD_PATTERNS = [
    r'\d{13,19}\s*[|/:-]\s*\d{1,2}\s*[|/:-]\s*\d{2,4}\s*[|/:-]\s*\d{3,4}',
    r'\d{13,19}\s*\|\s*\d{1,2}\s*\|\s*\d{2,4}\s*\|\s*\d{3,4}',
    r'\d{13,19}\s*/\s*\d{1,2}\s*/\s*\d{2,4}\s*/\s*\d{3,4}',
    r'\d{13,19}\s*:\s*\d{1,2}\s*:\s*\d{2,4}\s*:\s*\d{3,4}',
    r'\d{13,19}\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    r'\d{13,19}\s*\|\s*\d{1,2}\s*\|\s*\d{2,4}',
    r'\d{13,19}\s*/\s*\d{1,2}\s*/\s*\d{2,4}',
    r'\d{13,19}\s*:\s*\d{1,2}\s*:\s*\d{2,4}',
    r'\d{13,19}\s+\d{1,2}\s+\d{2,4}',
]


CARD_NUMBER_PATTERN = r'\b(\d{13,19})\b'

user_client = None
_invite_cache = {}





def luhn_check(card_number: str) -> bool:
    """Validate a card number using the Luhn algorithm."""
    if not card_number or len(card_number) < 13:
        return False
    
    digits = [int(d) for d in card_number if d.isdigit()]
    if len(digits) < 13:
        return False
    
    digits_rev = digits[::-1]
    total = 0
    for i, d in enumerate(digits_rev):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    
    return total % 10 == 0

def is_card_expired(month: str, year: str) -> bool:
    """Check if a card is expired based on MM/YY."""
    try:
        now = datetime.now()
        current_year = now.year % 100
        current_month = now.month
        
        month_int = int(month)
        year_int = int(year)
        
        if year_int < current_year:
            return True
        if year_int == current_year and month_int < current_month:
            return True
        return False
    except:
        return True





def extract_cards_from_text(text: str) -> List[str]:
    """Extract cards from text using multiple patterns."""
    if not text:
        return []
    
    cards = []
    
    for pattern in CARD_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            digits = re.findall(r'\d+', match)
            if len(digits) >= 4:
                card_number = digits[0]
                month = digits[1].zfill(2)
                year = digits[2]
                if len(year) == 4:
                    year = year[2:]
                cvv = digits[3] if len(digits) > 3 else "000"
                cards.append(f"{card_number}|{month}|{year}|{cvv}")
            elif len(digits) >= 3:
                card_number = digits[0]
                month = digits[1].zfill(2)
                year = digits[2]
                if len(year) == 4:
                    year = year[2:]
                cards.append(f"{card_number}|{month}|{year}|000")
    
    if not cards:
        matches = re.findall(CARD_NUMBER_PATTERN, text)
        for card_number in matches:
            if len(card_number) >= 13:
                cards.append(f"{card_number}|12|26|123")
    
    seen = set()
    unique_cards = []
    for card in cards:
        card_num = card.split('|')[0] if '|' in card else card
        if card_num not in seen:
            seen.add(card_num)
            unique_cards.append(card)
    
    return unique_cards

def validate_and_filter_cards(cards: List[str]) -> Tuple[List[str], dict]:
    """Validate cards, remove duplicates, filter expired and invalid cards."""
    seen = set()
    valid_cards = []
    invalid_cards = []
    expired_cards = []
    duplicate_count = 0
    
    stats = {
        "total": len(cards),
        "valid": 0,
        "invalid": 0,
        "expired": 0,
        "duplicates": 0,
        "card_types": {
            "visa": 0,
            "mastercard": 0,
            "amex": 0,
            "other": 0
        }
    }
    
    for card in cards:
        parts = card.split('|')
        if len(parts) < 4:
            invalid_cards.append(card)
            stats["invalid"] += 1
            continue
        
        card_number = parts[0]
        month = parts[1]
        year = parts[2]
        cvv = parts[3] if len(parts) > 3 else "000"
        
        if not card_number or len(card_number) < 13:
            invalid_cards.append(card)
            stats["invalid"] += 1
            continue
        
        if card_number in seen:
            duplicate_count += 1
            stats["duplicates"] += 1
            continue
        seen.add(card_number)
        
        if not luhn_check(card_number):
            invalid_cards.append(card)
            stats["invalid"] += 1
            continue
        
        if is_card_expired(month, year):
            expired_cards.append(card)
            stats["expired"] += 1
            continue
        
        if card_number.startswith('4'):
            stats["card_types"]["visa"] += 1
        elif card_number.startswith(('51', '52', '53', '54', '55')):
            stats["card_types"]["mastercard"] += 1
        elif card_number.startswith(('34', '37')):
            stats["card_types"]["amex"] += 1
        else:
            stats["card_types"]["other"] += 1
        
        valid_cards.append(card)
        stats["valid"] += 1
    
    return valid_cards, stats





async def initialize_pyrogram():
    global user_client
    if PYROGRAM_AVAILABLE and not user_client:
        try:
            if not SESSION_STRING:
                logger.error("SESSION_STRING not set in .env")
                return False
            
            user_client = PyrogramClient(
                "user_session",
                session_string=SESSION_STRING,
                api_id=API_ID,
                api_hash=API_HASH,
                workers=500
            )
            await user_client.start()
            
            try:
                me = await user_client.get_me()
                logger.info(f"✅ Pyrogram client started as: {me.first_name} (@{me.username})")
            except Exception as e:
                logger.warning(f"Could not get user info: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to start Pyrogram client: {e}")
            return False
    return False

async def stop_pyrogram():
    global user_client
    if user_client:
        try:
            await user_client.stop()
            logger.info("Pyrogram client stopped")
        except Exception as e:
            logger.error(f"Error stopping Pyrogram client: {e}")





def parse_channel_identifier(input_str: str) -> Tuple[str, str, str, str]:
    """Parse channel identifier from various formats.
    
    Returns:
        Tuple of (identifier, display_name, invite_hash, input_type)
        input_type: 'invite', 'username', 'chat_id'
    """
    input_str = input_str.strip()
    

    if "t.me/+" in input_str:
        invite_hash = input_str.split("t.me/+")[-1].split("/")[0]

        invite_hash = invite_hash.lstrip('+')
        logger.info(f"📌 Extracted invite hash: {invite_hash}")
        return invite_hash, f"Private Channel (+{invite_hash[:8]}...)", invite_hash, 'invite'
    

    if "t.me/" in input_str:
        username = input_str.split("t.me/")[-1].split("/")[0]
        if username.startswith("+"):
            invite_hash = username[1:].lstrip('+')
            return invite_hash, f"Private Channel (+{invite_hash[:8]}...)", invite_hash, 'invite'
        if not username.startswith("@"):
            username = "@" + username
        return username, username, None, 'username'
    

    if input_str.startswith("+"):
        invite_hash = input_str[1:].lstrip('+')
        return invite_hash, f"Private Channel (+{invite_hash[:8]}...)", invite_hash, 'invite'
    

    if input_str.startswith("@"):
        return input_str, input_str, None, 'username'
    

    if input_str.startswith("-100") and input_str.lstrip("-").isdigit():
        return input_str, f"Chat ID: {input_str}", None, 'chat_id'
    

    if input_str.isalnum() or "_" in input_str:
        return f"@{input_str}", f"@{input_str}", None, 'username'
    
    return input_str, input_str, None, 'unknown'





async def join_chat_safely(client, invite_hash: str):
    """Join a chat using invite hash with clean hash."""

    clean_hash = invite_hash.lstrip('+@')
    logger.info(f"🔑 Joining with clean hash: {clean_hash}")
    
    try:


        invite_url = f"https://t.me/+{clean_hash}"
        logger.info(f"📎 Using invite URL: {invite_url}")
        
        chat = await client.join_chat(invite_url)
        logger.info(f"✅ Joined channel: {chat.id} ({chat.title})")
        _invite_cache[clean_hash] = chat.id
        return chat
    except UserAlreadyParticipant:
        logger.info(f"✅ Already a member")
        try:

            chat = await client.get_chat(clean_hash)
            _invite_cache[clean_hash] = chat.id
            return chat
        except:

            try:
                invite_url = f"https://t.me/+{clean_hash}"
                chat = await client.get_chat(invite_url)
                _invite_cache[clean_hash] = chat.id
                return chat
            except:
                pass
                
            if clean_hash in _invite_cache:
                chat = await client.get_chat(_invite_cache[clean_hash])
                return chat
            raise ValueError("Cannot access channel")
    except InviteHashExpired:
        logger.warning(f"⚠️ Invite link expired: {clean_hash}")
        if clean_hash in _invite_cache:
            try:
                chat = await client.get_chat(_invite_cache[clean_hash])
                logger.info(f"✅ Retrieved expired chat from cache: {chat.id}")
                return chat
            except:
                pass
        raise ValueError("❌ Invite link expired. Please get a new one.")
    except InviteHashInvalid:
        raise ValueError("❌ Invalid invite link.")
    except InviteRequestSent:
        raise ValueError("📩 Join request sent. Please wait for approval.")
    except FloodWait as e:
        wait_time = e.value
        logger.warning(f"⏳ Flood wait: {wait_time} seconds")
        await asyncio.sleep(min(wait_time + 1, 30))

        try:
            invite_url = f"https://t.me/+{clean_hash}"
            chat = await client.join_chat(invite_url)
            _invite_cache[clean_hash] = chat.id
            return chat
        except:
            raise ValueError(f"⏳ Flood wait {wait_time}s. Try again later.")
    except Exception as e:
        logger.error(f"Join error: {e}")
        if clean_hash in _invite_cache:
            try:
                chat = await client.get_chat(_invite_cache[clean_hash])
                logger.info(f"✅ Retrieved from cache after error: {chat.id}")
                return chat
            except:
                pass
        raise ValueError(f"❌ Cannot join: {str(e)[:100]}")





async def get_chat_and_ensure_access(client, identifier: str, invite_hash: str = None, input_type: str = 'username'):
    """Get chat and ensure access with proper handling for all input types."""
    logger.info(f"📩 Getting chat: {identifier} (Type: {input_type})")
    



    if input_type == 'invite' and invite_hash:
        try:

            clean_hash = invite_hash.lstrip('+@')
            logger.info(f"🔑 Using clean invite hash: {clean_hash}")
            

            chat = await join_chat_safely(client, clean_hash)
            return chat
        
        except Exception as e:
            raise ValueError(f"❌ Error with invite: {str(e)[:100]}")
    



    elif input_type == 'username':
        try:

            chat = await client.get_chat(identifier)
            logger.info(f"✅ Chat found: {chat.id} ({chat.title})")
            return chat
        except UserNotParticipant:

            try:
                chat = await client.join_chat(identifier)
                logger.info(f"✅ Joined: {chat.id} ({chat.title})")
                return chat
            except InviteRequestSent:
                raise ValueError("📩 Join request sent. Please wait for approval.")
            except Exception as e:
                raise ValueError(f"❌ Cannot join {identifier}: {str(e)[:100]}")
        except UsernameNotOccupied:
            raise ValueError(f"❌ Username {identifier} not found")
        except Exception as e:
            raise ValueError(f"❌ Cannot access {identifier}: {str(e)[:100]}")
    



    elif input_type == 'chat_id':
        try:

            chat = await client.get_chat(int(identifier))
            logger.info(f"✅ Chat found: {chat.id} ({chat.title})")
            return chat
        except UserNotParticipant:
            raise ValueError(f"❌ Bot is not a member of chat {identifier}. Please use an invite link or username.")
        except PeerIdInvalid:
            raise ValueError(f"❌ Invalid chat ID: {identifier}. Please use an invite link or username.")
        except Exception as e:
            raise ValueError(f"❌ Cannot access chat {identifier}: {str(e)[:100]}")
    



    else:
        raise ValueError(f"❌ Unrecognized identifier: {identifier}")





async def scrape_messages(client, channel_identifier: str, limit: int, bin_filter: str = None, bank_filter: str = None, invite_hash: str = None, input_type: str = 'username'):
    """Scrape messages from a channel/group."""
    start_time = time.time()
    all_cards = []
    processed = 0
    errors = 0
    
    try:
        chat = await get_chat_and_ensure_access(client, channel_identifier, invite_hash, input_type)
        chat_id = chat.id
        
        logger.info(f"📖 Scraping from chat: {chat.id} ({chat.title})")
        
        offset_id = 0
        batch_size = 100
        max_retries = 3
        retry_count = 0
        
        while len(all_cards) < limit:
            try:
                history = client.get_chat_history(
                    chat_id,
                    limit=batch_size,
                    offset_id=offset_id,
                )
                
                batch = []
                async for message in history:
                    batch.append(message)
                
                if not batch:
                    logger.info(f"✅ No more messages (scanned {processed} total)")
                    break
                
                for message in batch:
                    if len(all_cards) >= limit:
                        break
                    
                    processed += 1
                    text = message.text or message.caption or ""
                    
                    if processed <= 5:
                        logger.info(f"📝 Sample msg {processed}: {text[:100] if text else 'No text'}")
                    
                    if text:
                        if bank_filter and bank_filter.lower() not in text.lower():
                            continue
                        
                        cards = extract_cards_from_text(text)
                        
                        if bin_filter and cards:
                            cards = [c for c in cards if c.split('|')[0].startswith(bin_filter[:6])]
                        
                        if cards:
                            logger.info(f"✅ Found {len(cards)} cards in msg {processed}")
                            all_cards.extend(cards)
                            if len(all_cards) >= limit:
                                break
                
                if batch:
                    offset_id = batch[-1].id
                    retry_count = 0
                
                logger.info(f"📦 Batch: {processed} msgs → {len(all_cards)} total cards")
                await asyncio.sleep(0.1)
                
            except FloodWait as e:
                wait_time = e.value
                logger.warning(f"⏳ Flood wait: {wait_time} seconds")
                await asyncio.sleep(min(wait_time + 1, 30))
                continue
            except Exception as e:
                retry_count += 1
                logger.warning(f"⚠️ Batch error (attempt {retry_count}/{max_retries}): {e}")
                if retry_count >= max_retries:
                    logger.error(f"❌ Max retries reached, stopping scrape")
                    break
                await asyncio.sleep(2)
                continue
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Scraped {len(all_cards)} raw cards from {processed} messages in {elapsed:.2f}s")
        
        valid_cards, stats = validate_and_filter_cards(all_cards)
        
        logger.info(f"📊 Card stats: Total={stats['total']}, Valid={stats['valid']}, "
                   f"Invalid={stats['invalid']}, Expired={stats['expired']}, Duplicates={stats['duplicates']}")
        
        return valid_cards, stats
        
    except Exception as e:
        logger.error(f"Scrape error: {e}")
        raise





@check_lock
@rate_limit("gate")
async def handle_scr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scr command - Scrape cards from channel/group."""
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name


    if not is_premium(user_id):
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙋𝙍𝙀𝙈𝙄𝙐𝙈 𝙍𝙀𝙌𝙐𝙄𝙍𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Scraper is only available for premium users.

Use /redeem to activate your premium key.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if not PYROGRAM_AVAILABLE:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙋𝙔𝙍𝙊𝙂𝙍𝘼𝙈 𝙉𝙊𝙏 𝘼𝙑𝘼𝙄𝙇𝘼𝘽𝙇𝙀 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Please install pyrogram:
<code>pip install pyrogram</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝙈𝙄𝙎𝙎𝙄𝙉𝙂 𝘼𝙍𝙂𝙐𝙈𝙀𝙉𝙏𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} <b>Usage:</b>

<b>By Username:</b>
<code>/scr @channel 100</code>

<b>By Invite Link:</b>
<code>/scr https://t.me/+invite_hash 100</code>
<code>/scr +invite_hash 100</code>

<b>By Chat ID:</b>
<code>/scr -100123456789 100</code>

<b>With Filters:</b>
<code>/scr @channel 100 515462</code>  → BIN filter
<code>/scr @channel 100 "Bank Name"</code> → Bank filter
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    raw_identifier = args[0]
    channel_identifier, display_name, invite_hash, input_type = parse_channel_identifier(raw_identifier)
    
    logger.info(f"📌 Raw: {raw_identifier} → Parsed: {channel_identifier}, Hash: {invite_hash}, Type: {input_type}")

    try:
        limit = int(args[1])
    except ValueError:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙄𝙉𝙑𝘼𝙇𝙄𝘿 𝙇𝙄𝙈𝙄𝙏 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Invalid limit value.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    if limit > 5000:
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝙇𝙄𝙈𝙄𝙏 𝙀𝙓𝘾𝙀𝙀𝘿𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Maximum limit is 5000 cards.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    bin_filter = args[2] if len(args) > 2 and args[2].isdigit() else None
    bank_filter = " ".join(args[2:]) if len(args) > 2 and not args[2].isdigit() else None

    progress = await update.message.reply_text(
        f"""
{E.FLY} ⌠ 𝙎𝘾𝙍𝘼𝙋𝙄𝙉𝙂 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Source</b> ↬ <code>{display_name}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Type</b> ↬ <code>{input_type.upper()}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Limit</b> ↬ <code>{limit}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>BIN Filter</b> ↬ <code>{bin_filter or 'None'}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Bank Filter</b> ↬ <code>{bank_filter or 'None'}</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    async def update_progress(text: str):
        try:
            await progress.edit_text(
                f"""
{E.FLY} ⌠ 𝙎𝘾𝙍𝘼𝙋𝙄𝙉𝙂 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Source</b> ↬ <code>{display_name}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Status</b> ↬ <code>{text}</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception:
            pass

    async def background():
        if not user_client or not user_client.is_connected:
            success = await initialize_pyrogram()
            if not success:
                await progress.edit_text(
                    f"""
{E.ERROR} ⌠ 𝙁𝘼𝙄𝙇𝙀𝘿 𝙏𝙊 𝘾𝙊𝙉𝙉𝙀𝘾𝙏 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Could not initialize Pyrogram.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                return

        try:
            valid_cards, stats = await scrape_messages(
                user_client,
                channel_identifier,
                limit,
                bin_filter,
                bank_filter,
                invite_hash,
                input_type
            )

            if valid_cards:
                random.shuffle(valid_cards)
                
                file_content = "\n".join(valid_cards)
                file = io.BytesIO(file_content.encode('utf-8'))
                file_name = f"OGGY_{len(valid_cards)}.txt"
                file.name = file_name

                card_types = stats.get("card_types", {})
                stats_text = f"""
{E.SUCCESS} ⌠ 𝙎𝘾𝙍𝘼𝙋𝙄𝙉𝙂 𝘾𝙊𝙈𝙋𝙇𝙀𝙏𝙀 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Valid Cards</b> ↬ <code>{stats['valid']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Invalid</b> ↬ <code>{stats['invalid']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Expired</b> ↬ <code>{stats['expired']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Duplicates</b> ↬ <code>{stats['duplicates']}</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Visa</b> ↬ <code>{card_types.get('visa', 0)}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Mastercard</b> ↬ <code>{card_types.get('mastercard', 0)}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Amex</b> ↬ <code>{card_types.get('amex', 0)}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Other</b> ↬ <code>{card_types.get('other', 0)}</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>Source</b> ↬ <code>{display_name}</code>
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

                await context.bot.send_document(
                    update.effective_chat.id,
                    document=file,
                    caption=stats_text,
                    parse_mode="HTML",
                )
                file.close()
                await progress.delete()
            else:
                error_msg = f"""
{E.WARNING} ⌠ 𝙉𝙊 𝙑𝘼𝙇𝙄𝘿 𝘾𝘼𝙍𝘿𝙎 𝙁𝙊𝙐𝙉𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} No valid credit cards found in <code>{display_name}</code>.

<b>Scrape Stats:</b>
<a href='https://t.me/oggyproo'>⊀</a> <b>Total found</b> ↬ <code>{stats['total']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Invalid</b> ↬ <code>{stats['invalid']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Expired</b> ↬ <code>{stats['expired']}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Duplicates</b> ↬ <code>{stats['duplicates']}</code>
━━━━━━━━━━━━━━━━━━
<b>Possible reasons:</b>
• No valid cards in the channel
• Cards are in images/attachments
• Filters are too strict
• Channel/group is private
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

                await progress.edit_text(
                    error_msg,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )

        except ValueError as e:
            await progress.edit_text(
                f"""
{E.INFO} ⌠ 𝙀𝙍𝙍𝙊𝙍 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception as e:
            logger.error(f"Scraping error: {e}")
            await progress.edit_text(
                f"""
{E.ERROR} ⌠ 𝙀𝙍𝙍𝙊𝙍 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)[:200]}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )

    asyncio.create_task(background())





def register_scr(app):
    """Register /scr command handler."""
    app.add_handler(CommandHandler("scr", handle_scr_command))
    logger.info("✅ /scr registered")