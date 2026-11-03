

import re
import random
import time
import io
import asyncio
from typing import List, Dict, Tuple, Optional

from bin import get_bin_info
from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from config import OWNER_USERNAME, OWNER_NAME
from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes

logger = get_logger(__name__)





def luhn_check(card_number: str) -> bool:
    """Validate a card number using the Luhn algorithm."""
    digits = [int(d) for d in card_number]
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] = (digits[i] // 10) + (digits[i] % 10)
    return sum(digits) % 10 == 0


def generate_luhn_card(prefix: str, length: int = 16) -> str:
    """Generate a valid credit card number using the Luhn algorithm."""
    card = prefix
    while len(card) < length - 1:
        card += str(random.randint(0, 9))
    for i in range(10):
        test_card = card + str(i)
        if luhn_check(test_card):
            return test_card
    return card + "0"






def parse_gen_input(input_text: str) -> Tuple[str, str, str, int, str]:
    """Parse the input for the gen command."""
    bin_pattern = ""
    month = "rnd"
    year = "rnd"
    amount = 10
    cvv = "rnd"
    
    if "|" in input_text:
        parts = input_text.split("|")
        if len(parts) > 0:
            bin_pattern = parts[0].strip()
        if len(parts) > 1:
            month = parts[1].strip()
            if month.lower() == "rnd":
                month = "rnd"
        if len(parts) > 2:
            year = parts[2].strip()
            if year.lower() == "rnd":
                year = "rnd"
            elif len(year) == 4:
                year = year[2:]
        if len(parts) > 3:
            part4 = parts[3].strip()
            if part4.lower() == "rnd":
                cvv = "rnd"
            else:
                try:
                    test_amount = int(part4)
                    if test_amount > 0:
                        amount = test_amount
                    else:
                        cvv = part4
                except ValueError:
                    cvv = part4
        if len(parts) > 4:
            try:
                test_amount = int(parts[4].strip())
                if test_amount > 0:
                    amount = test_amount
            except ValueError:
                pass
    else:
        parts = input_text.split()
        if len(parts) > 0:
            bin_pattern = parts[0].strip()
        if len(parts) > 1:
            try:
                test_amount = int(parts[1].strip())
                if test_amount > 0:
                    amount = test_amount
                else:
                    month = parts[1].strip()
            except ValueError:
                month = parts[1].strip()
        if len(parts) > 2 and month != "rnd":
            year = parts[2].strip()
            if year.lower() == "rnd":
                year = "rnd"
            elif len(year) == 4:
                year = year[2:]
        if len(parts) > 3 and month != "rnd" and year != "rnd":
            cvv = parts[3].strip()
            if cvv.lower() == "rnd":
                cvv = "rnd"
        if len(parts) > 4:
            try:
                test_amount = int(parts[4].strip())
                if test_amount > 0:
                    amount = test_amount
            except ValueError:
                pass
    
    if not bin_pattern or len(bin_pattern) < 6:
        raise ValueError("BIN must be at least 6 digits long")
    
    return bin_pattern, month, year, amount, cvv






async def generate_cards(bin_pattern: str, month: str, year: str, amount: int, cvv: str) -> Tuple[List[str], Dict]:
    """Generate credit cards with BIN information."""
    bin_number = bin_pattern[:6]
    bin_info = await get_bin_info(bin_number)
    
    is_amex = bin_info.get("scheme", "").lower() == "american express" or bin_pattern.startswith(("34", "37"))
    
    cards = []
    for _ in range(amount):
        if month.lower() == "rnd":
            card_month = str(random.randint(1, 12)).zfill(2)
        else:
            card_month = month
        
        if year.lower() == "rnd":
            current_year = time.strftime("%y")
            card_year = str(random.randint(int(current_year), int(current_year) + 7)).zfill(2)
        else:
            card_year = year
        
        card_length = 15 if is_amex else 16
        card_number = generate_luhn_card(bin_pattern, card_length)
        
        if cvv.lower() == "rnd":
            card_cvv = str(random.randint(1000, 9999)) if is_amex else str(random.randint(100, 999))
        else:
            card_cvv = cvv
            if is_amex and len(card_cvv) == 3:
                card_cvv = card_cvv + str(random.randint(0, 9))
            elif not is_amex and len(card_cvv) == 4:
                card_cvv = card_cvv[:3]
        
        cards.append(f"{card_number}|{card_month}|{card_year}|{card_cvv}")
    
    return cards, bin_info






def format_gen_response(cards: List[str], bin_info: Dict, bin_pattern: str, amount: int) -> str:
    brand = (bin_info.get("scheme") or "N/A").title()
    level = bin_info.get("level", "")
    card_type = bin_info.get("type", "")
    
    brand_parts = [brand]
    if level:
        brand_parts.append(level)
    if card_type:
        brand_parts.append(card_type)
    brand_display = " - ".join(brand_parts)
    
    bank = bin_info.get("bank") or "N/A"
    country = bin_info.get("country") or "Unknown"
    country_flag = bin_info.get("country_emoji", "")
    
    display_cards = cards[:30] if len(cards) > 30 else cards
    card_list = "\n".join([f"<code>{card}</code>" for card in display_cards])
    
    if len(cards) > 30:
        card_list += f"\n\n<code>... and {len(cards) - 30} more cards</code>"
    
    return f"""
{E.SUCCESS} ⌠ 𝘾𝘼𝙍𝘿 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙊𝙍 ⌡
━━━━━━━━━━━━━━━━━━
{E.CARD} Generated <b>{len(cards)}</b> Cards

{card_list}

<pre>
┌─ Brand   : {brand_display}
├─ Bank    : {bank}
├─ Country : {country_flag} {country}
└─ Type    : {card_type}
</pre>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""


def format_gen_file_caption(bin_info: Dict, bin_pattern: str, amount: int) -> str:
    brand = (bin_info.get("scheme") or "N/A").title()
    level = bin_info.get("level", "")
    card_type = bin_info.get("type", "")
    
    brand_parts = [brand]
    if level:
        brand_parts.append(level)
    if card_type:
        brand_parts.append(card_type)
    brand_display = " - ".join(brand_parts)
    
    bank = bin_info.get("bank") or "N/A"
    country = bin_info.get("country") or "Unknown"
    country_flag = bin_info.get("country_emoji", "")
    
    return f"""
{E.SUCCESS} ⌠ 𝘾𝘼𝙍𝘿 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙊𝙍 ⌡
━━━━━━━━━━━━━━━━━━
{E.CARD} Generated <b>{amount}</b> Cards

<pre>
┌─ BIN     : {bin_pattern[:6]}
├─ Brand   : {brand_display}
├─ Bank    : {bank}
├─ Country : {country_flag} {country}
└─ Type    : {card_type}
</pre>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""






@check_lock
@rate_limit("gate")
async def handle_gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate credit cards with valid Luhn numbers."""
    user = update.effective_user
    user_id = user.id
    
    input_text = " ".join(context.args)
    
    if not input_text:
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝙈𝙄𝙎𝙎𝙄𝙉𝙂 𝘽𝙄𝙉 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} <b>Usage:</b>
<code>/gen 486732</code>
<code>/gen 486732|12|26|123|50</code>

<b>Format:</b>
<code>BIN|MM|YY|CVV|Amount</code>

<b>Example:</b>
<code>/gen 486732|rnd|rnd|rnd|20</code>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    
    try:
        bin_pattern, month, year, amount, cvv = parse_gen_input(input_text)
    except ValueError as e:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙀𝙍𝙍𝙊𝙍 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    
    if amount > 50000:
        await update.message.reply_text(
            f"""
{E.WARNING} ⌠ 𝙏𝙊𝙊 𝙈𝘼𝙉𝙔 𝘾𝘼𝙍𝘿𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Maximum allowed is 50,000 cards.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return
    
    progress = await update.message.reply_text(
        f"""
{E.FLY} ⌠ 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙄𝙉𝙂 ⌡
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⊀</a> <b>BIN</b> ↬ <code>{bin_pattern[:6]}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>Amount</b> ↬ <code>{amount}</code> cards
<i>Generating...</i>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    
    async def background():
        try:
            cards, bin_info = await generate_cards(bin_pattern, month, year, amount, cvv)
            
            if amount > 20:
                file_content = "\n".join(cards)
                file = io.BytesIO(file_content.encode('utf-8'))
                file.name = f"OGGY_{bin_pattern[:6]}.txt"
                
                caption = format_gen_file_caption(bin_info, bin_pattern, amount)
                

                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=file,
                    caption=caption,
                    parse_mode="HTML",
                )
                await progress.delete()
            else:
                formatted = format_gen_response(cards, bin_info, bin_pattern, amount)
                await progress.edit_text(
                    formatted,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                
        except Exception as e:
            logger.error(f"Gen command error: {e}")
            await progress.edit_text(
                f"""
{E.ERROR} ⌠ 𝙀𝙍𝙍𝙊𝙍 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
    
    asyncio.create_task(background())