


import io
import re
import random
import asyncio
from datetime import datetime
from typing import List, Tuple, Optional
from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from utils.rate_limit import rate_limit
from utils.lock_check import check_lock
from logger import get_logger
from ui.emojis import PremiumEmoji as E
from ui.emojis import ButtonEmoji as BE
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID, BOT_USERNAME

logger = get_logger(__name__)





MAX_FILE_SIZE = 20 * 1024 * 1024
CARD_PATTERN = re.compile(
    r'(\d{13,19})\s*[|/:]\s*(\d{1,2})\s*[|/:]\s*(\d{2,4})\s*[|/:]\s*(\d{3,4})'
)


merge_sessions = {}
PART_SESSIONS = {}
SPLIT_SESSIONS = {}


def check_file_size(file_size: int) -> Optional[str]:
    """Check if file size exceeds limit. Returns error message or None."""
    if file_size > MAX_FILE_SIZE:
        return f"File too large ({file_size // (1024*1024)} MB). Maximum allowed: 20 MB."
    return None






@check_lock
@rate_limit("gate")
async def merge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Merge multiple files - send files one by one, type /done when finished."""
    user = update.effective_user
    user_id = user.id

    if user_id in merge_sessions:
        await update.message.reply_text(
            f"""
{E.WARNING} <b>Active Merge Session</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} You already have an active merge session.

Type <code>/done</code> to finish merging,
or <code>/cancel</code> to cancel.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    merge_sessions[user_id] = {
        "files": [],
        "total_lines": 0,
        "start_time": datetime.now()
    }

    await update.message.reply_text(
        f"""
{E.FILE} <b>Merge Files</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Send me the files you want to merge one by one.

<b>How to use:</b>
1️⃣ Send a .txt file (max 20 MB each)
2️⃣ Send another .txt file
3️⃣ Type <code>/done</code> when finished
4️⃣ Type <code>/cancel</code> to cancel

<b>Current session:</b>
{E.FILE} Files: <code>0</code>
{E.CLOCK} Lines: <code>0</code>

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
    return


async def handle_merge_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file upload during merge session."""
    user = update.effective_user
    user_id = user.id

    if user_id not in merge_sessions:
        return

    if not update.message.document:
        return


    file_size = update.message.document.file_size or 0
    error = check_file_size(file_size)
    if error:
        await update.message.reply_text(
            f"{E.ERROR} <b>File Rejected</b>\n\n{error}\n\nMax: 20 MB",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    file_name = update.message.document.file_name or "unknown.txt"

    if not file_name.lower().endswith((".txt", ".csv", ".text", ".log")):
        await update.message.reply_text(
            f"{E.ERROR} Please send a .txt file. Received: <code>{file_name}</code>",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    progress = await update.message.reply_text(
        f"{E.FLY} Reading <code>{file_name}</code>...",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    try:
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        text = file_content.decode('utf-8', errors='ignore')
        lines = text.splitlines()
        line_count = len(lines)

        session = merge_sessions[user_id]
        session["files"].append({
            "name": file_name,
            "content": text,
            "lines": line_count
        })
        session["total_lines"] += line_count

        await progress.edit_text(
            f"""
{E.SUCCESS} <b>File Added!</b>
━━━━━━━━━━━━━━━━━━
{E.FILE} <b>File:</b> <code>{file_name}</code>
{E.CLOCK} <b>Lines:</b> <code>{line_count}</code>
━━━━━━━━━━━━━━━━━━
{E.FILE} <b>Total Files:</b> <code>{len(session['files'])}</code>
{E.CLOCK} <b>Total Lines:</b> <code>{session['total_lines']}</code>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Send another file or type <code>/done</code> to finish.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

    except Exception as e:
        await progress.edit_text(
            f"""
{E.ERROR} <b>Failed to read file</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)[:100]}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )


@check_lock
@rate_limit("gate")
async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish merge session and create merged file."""
    user = update.effective_user
    user_id = user.id

    if user_id not in merge_sessions:
        await update.message.reply_text(
            f"""
{E.WARNING} <b>No Active Merge Session</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Start a merge session with <code>/merge</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    session = merge_sessions[user_id]

    if not session["files"]:
        await update.message.reply_text(
            f"""
{E.WARNING} <b>No Files Added</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} You haven't added any files to merge.

Send some files first, then type <code>/done</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    progress = await update.message.reply_text(
        f"{E.FLY} Merging {len(session['files'])} files...",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    try:
        merged_content = f"MERGED FILE\n"
        merged_content += "=" * 50 + "\n"
        merged_content += f"Files: {len(session['files'])}\n"
        merged_content += f"Total Lines: {session['total_lines']}\n"
        merged_content += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        merged_content += "=" * 50 + "\n\n"

        for i, file_data in enumerate(session['files'], 1):
            merged_content += f"--- File {i}: {file_data['name']} ---\n"
            merged_content += file_data['content']
            if not merged_content.endswith('\n'):
                merged_content += '\n'
            merged_content += "\n" + "-" * 40 + "\n\n"

        file_io = io.BytesIO(merged_content.encode('utf-8'))
        file_io.name = f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        await progress.delete()

        await update.message.reply_document(
            document=file_io,
            caption=f"""
{E.SUCCESS} <b>Merge Complete!</b>
━━━━━━━━━━━━━━━━━━
{E.FILE} <b>Files:</b> <code>{len(session['files'])}</code>
{E.CLOCK} <b>Lines:</b> <code>{session['total_lines']}</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
{E.LINK} @{OWNER_USERNAME}""",
            parse_mode="HTML"
        )
        file_io.close()

        del merge_sessions[user_id]

    except Exception as e:
        logger.error(f"Merge error: {e}")
        await progress.edit_text(
            f"""
{E.ERROR} <b>Merge Failed</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)[:100]}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )


@check_lock
@rate_limit("gate")
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel merge session."""
    user = update.effective_user
    user_id = user.id

    if user_id in merge_sessions:
        del merge_sessions[user_id]
        await update.message.reply_text(
            f"""
{E.CLOSE} <b>Merge Session Cancelled</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Your merge session has been cancelled.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
    else:
        await update.message.reply_text(
            f"""
{E.WARNING} <b>No Active Merge Session</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} You don't have an active merge session.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )






@check_lock
@rate_limit("gate")
async def split_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Split a file into chunks by lines."""
    user = update.effective_user
    user_id = user.id


    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            f"""
{E.INFO} <b>Split File</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Reply to a .txt file (max 20 MB) with:

<code>/split 500</code> - 500 lines per file
<code>/split</code> - I'll ask how many lines

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    file_size = update.message.reply_to_message.document.file_size or 0
    error = check_file_size(file_size)
    if error:
        await update.message.reply_text(
            f"{E.ERROR} <b>File Rejected</b>\n\n{error}\n\nMax: 20 MB",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    if context.args and context.args[0].isdigit():
        lines_per_file = int(context.args[0])
        if lines_per_file < 10:
            lines_per_file = 10
        if lines_per_file > 100000:
            lines_per_file = 100000

        await process_split(update, context, update.message.reply_to_message.document.file_id, lines_per_file)
        return


    file_id = update.message.reply_to_message.document.file_id
    file_name = update.message.reply_to_message.document.file_name or "file.txt"

    SPLIT_SESSIONS[user_id] = {
        "file_id": file_id,
        "file_name": file_name
    }

    await update.message.reply_text(
        f"""
{E.INFO} <b>How Many Lines Per File?</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Reply with a number (minimum 10 lines):

Example: <code>1000</code> - 1000 lines per file

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    return


async def process_split(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, lines_per_file: int):
    """Process splitting file."""
    user = update.effective_user
    progress = await update.message.reply_text(
        f"{E.FLY} Splitting file...",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    try:
        file = await context.bot.get_file(file_id)
        file_content = await file.download_as_bytearray()
        text = file_content.decode('utf-8', errors='ignore')
        lines = text.splitlines()
        total_lines = len(lines)

        if total_lines == 0:
            await progress.edit_text(f"{E.ERROR} File is empty.", parse_mode="HTML")
            return

        chunks = [lines[i:i + lines_per_file] for i in range(0, total_lines, lines_per_file)]
        total_chunks = len(chunks)

        await progress.edit_text(
            f"""
{E.FLY} Splitting {total_lines} lines into {total_chunks} chunks...
━━━━━━━━━━━━━━━━━━
{E.CLOCK} <b>Total Lines:</b> <code>{total_lines}</code>
{E.FILE} <b>Chunks:</b> <code>{total_chunks}</code>
{E.CLOCK} <b>Per file:</b> <code>{lines_per_file}</code>
━━━━━━━━━━━━━━━━━━
<i>Sending files...</i>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

        for i, chunk in enumerate(chunks, 1):
            content = "\n".join(chunk)
            file_io = io.BytesIO(content.encode('utf-8'))
            file_io.name = f"chunk_{i}_of_{total_chunks}.txt"

            await update.message.reply_document(
                document=file_io,
                caption=f"""
{E.FILE} Chunk {i}/{total_chunks}
{E.CLOCK} Lines: {len(chunk)}
{E.DEV} <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML"
            )
            file_io.close()

        await progress.delete()

        user_id = user.id
        if user_id in SPLIT_SESSIONS:
            del SPLIT_SESSIONS[user_id]

    except Exception as e:
        logger.error(f"Split error: {e}")
        await progress.edit_text(
            f"""
{E.ERROR} <b>Split Failed</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)[:100]}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )






@check_lock
@rate_limit("gate")
async def parts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Split a file into N parts."""
    user = update.effective_user
    user_id = user.id


    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            f"""
{E.INFO} <b>Split into Parts</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Reply to a .txt file (max 20 MB) with:

<code>/parts 5</code> - Split into 5 files
<code>/parts</code> - I'll ask how many parts

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    file_size = update.message.reply_to_message.document.file_size or 0
    error = check_file_size(file_size)
    if error:
        await update.message.reply_text(
            f"{E.ERROR} <b>File Rejected</b>\n\n{error}\n\nMax: 20 MB",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    if context.args and context.args[0].isdigit():
        num_parts = int(context.args[0])
        if num_parts < 2:
            num_parts = 2
        if num_parts > 100:
            num_parts = 100

        await process_parts(update, context, update.message.reply_to_message.document.file_id, num_parts)
        return


    file_id = update.message.reply_to_message.document.file_id
    file_name = update.message.reply_to_message.document.file_name or "file.txt"

    PART_SESSIONS[user_id] = {
        "file_id": file_id,
        "file_name": file_name
    }

    await update.message.reply_text(
        f"""
{E.INFO} <b>How Many Parts?</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Reply with a number between 2-100:

Example: <code>5</code> - Split into 5 parts

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    return


async def process_parts(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, num_parts: int):
    """Process splitting file into parts."""
    user = update.effective_user
    progress = await update.message.reply_text(
        f"{E.FLY} Splitting into {num_parts} parts...",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    try:
        file = await context.bot.get_file(file_id)
        file_content = await file.download_as_bytearray()
        text = file_content.decode('utf-8', errors='ignore')
        lines = text.splitlines()
        total_lines = len(lines)

        if total_lines == 0:
            await progress.edit_text(f"{E.ERROR} File is empty.", parse_mode="HTML")
            return

        lines_per_part = total_lines // num_parts
        remainder = total_lines % num_parts

        chunks = []
        start = 0
        for i in range(num_parts):
            end = start + lines_per_part + (1 if i < remainder else 0)
            chunks.append(lines[start:end])
            start = end

        total_chunks = len(chunks)

        await progress.edit_text(
            f"""
{E.FLY} Splitting {total_lines} lines into {total_chunks} parts...
━━━━━━━━━━━━━━━━━━
{E.CLOCK} <b>Total Lines:</b> <code>{total_lines}</code>
{E.FILE} <b>Parts:</b> <code>{total_chunks}</code>
━━━━━━━━━━━━━━━━━━
<i>Sending files...</i>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

        for i, chunk in enumerate(chunks, 1):
            content = "\n".join(chunk)
            file_io = io.BytesIO(content.encode('utf-8'))
            file_io.name = f"part_{i}_of_{total_chunks}.txt"

            await update.message.reply_document(
                document=file_io,
                caption=f"""
{E.FILE} Part {i}/{total_chunks}
{E.CLOCK} Lines: {len(chunk)}
{E.DEV} <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML"
            )
            file_io.close()

        await progress.delete()

        user_id = user.id
        if user_id in PART_SESSIONS:
            del PART_SESSIONS[user_id]

    except Exception as e:
        logger.error(f"Parts error: {e}")
        await progress.edit_text(
            f"""
{E.ERROR} <b>Split Failed</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)[:100]}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )






def extract_cards_from_text(text: str) -> List[str]:
    """Extract card details from text."""
    cards = []
    for match in CARD_PATTERN.finditer(text):
        card_number, month, year, cvv = match.groups()
        month = month.zfill(2)
        if len(year) == 4:
            year = year[2:]
        cards.append(f"{card_number}|{month}|{year}|{cvv}")
    return cards


def clean_cards(cards: List[str]) -> Tuple[List[str], List[str]]:
    """Clean cards: remove duplicates and expired cards."""
    seen = set()
    valid_cards = []
    expired_cards = []

    for card in cards:
        if card in seen:
            continue
        seen.add(card)

        parts = card.split('|')
        if len(parts) == 4:
            _, month, year, _ = parts
            if is_card_expired(month, year):
                expired_cards.append(card)
                continue

        valid_cards.append(card)

    return valid_cards, expired_cards


def is_card_expired(month: str, year: str) -> bool:
    """Check if card is expired based on MM/YY."""
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


@check_lock
@rate_limit("gate")
async def clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clean cards: remove duplicates and expired (only for CC)."""
    user = update.effective_user

    text = None
    file_size = 0

    if update.message.reply_to_message:
        if update.message.reply_to_message.document:

            file_size = update.message.reply_to_message.document.file_size or 0
            error = check_file_size(file_size)
            if error:
                await update.message.reply_text(
                    f"{E.ERROR} <b>File Rejected</b>\n\n{error}\n\nMax: 20 MB",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                return
            try:
                file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
                file_content = await file.download_as_bytearray()
                text = file_content.decode('utf-8', errors='ignore')
            except Exception as e:
                await update.message.reply_text(f"{E.ERROR} Failed to read file: {str(e)}", parse_mode="HTML")
                return
        elif update.message.reply_to_message.text:
            text = update.message.reply_to_message.text
        elif update.message.reply_to_message.caption:
            text = update.message.reply_to_message.caption
    elif update.message.text:
        text = update.message.text

    if not text:
        await update.message.reply_text(
            f"""
{E.INFO} <b>Clean Cards</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Reply to a .txt file (max 20 MB) or message with <code>/clean</code>

<b>What it does:</b>
• Extracts card details only
• Removes duplicates
• Removes expired cards
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    progress = await update.message.reply_text(
        f"{E.FLY} Extracting cards...",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    try:
        raw_cards = extract_cards_from_text(text)

        if not raw_cards:
            await progress.edit_text(f"{E.ERROR} No valid cards found.", parse_mode="HTML")
            return

        valid_cards, expired_cards = clean_cards(raw_cards)
        duplicates = len(raw_cards) - len(valid_cards) - len(expired_cards)

        content = "\n".join(valid_cards)
        file_io = io.BytesIO(content.encode('utf-8'))
        file_io.name = f"cleaned_cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        await progress.edit_text(
            f"""
{E.SUCCESS} <b>Clean Complete!</b>
━━━━━━━━━━━━━━━━━━
{E.CARD} <b>Original:</b> <code>{len(raw_cards)}</code>
{E.APPROVED} <b>Valid:</b> <code>{len(valid_cards)}</code>
{E.DECLINED} <b>Expired:</b> <code>{len(expired_cards)}</code>
{E.ERROR} <b>Duplicates:</b> <code>{duplicates}</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

        await update.message.reply_document(
            document=file_io,
            caption=f"""
{E.APPROVED} Cleaned Cards: {len(valid_cards)}
{E.DEV} <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML"
        )
        file_io.close()

    except Exception as e:
        logger.error(f"Clean error: {e}")
        await progress.edit_text(
            f"""
{E.ERROR} <b>Clean Failed</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)[:100]}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )






@check_lock
@rate_limit("gate")
async def shuffle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shuffle lines randomly (any text file)."""
    user = update.effective_user

    text = None
    file_size = 0

    if update.message.reply_to_message:
        if update.message.reply_to_message.document:

            file_size = update.message.reply_to_message.document.file_size or 0
            error = check_file_size(file_size)
            if error:
                await update.message.reply_text(
                    f"{E.ERROR} <b>File Rejected</b>\n\n{error}\n\nMax: 20 MB",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                return
            try:
                file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
                file_content = await file.download_as_bytearray()
                text = file_content.decode('utf-8', errors='ignore')
            except Exception as e:
                await update.message.reply_text(f"{E.ERROR} Failed to read file: {str(e)}", parse_mode="HTML")
                return
        elif update.message.reply_to_message.text:
            text = update.message.reply_to_message.text
        elif update.message.reply_to_message.caption:
            text = update.message.reply_to_message.caption
    elif update.message.text:
        text = update.message.text

    if not text:
        await update.message.reply_text(
            f"""
{E.INFO} <b>Shuffle File</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} Reply to a .txt file (max 20 MB) or message with <code>/shuffle</code>

<b>What it does:</b>
• Shuffles all lines randomly
• Works with any text file
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return

    progress = await update.message.reply_text(
        f"{E.FLY} Shuffling...",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    try:
        lines = text.splitlines()
        random.shuffle(lines)

        content = "\n".join(lines)
        file_io = io.BytesIO(content.encode('utf-8'))
        file_io.name = f"shuffled_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        await progress.edit_text(
            f"""
{E.SUCCESS} <b>Shuffle Complete!</b>
━━━━━━━━━━━━━━━━━━
{E.CLOCK} <b>Total Lines:</b> <code>{len(lines)}</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

        await update.message.reply_document(
            document=file_io,
            caption=f"""
{E.REFRESH} Shuffled: {len(lines)} lines
{E.DEV} <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML"
        )
        file_io.close()

    except Exception as e:
        logger.error(f"Shuffle error: {e}")
        await progress.edit_text(
            f"""
{E.ERROR} <b>Shuffle Failed</b>
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)[:100]}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )






async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for parts/split commands."""

    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()


    if user_id in PART_SESSIONS:
        if text.isdigit():
            num_parts = int(text)
            if 2 <= num_parts <= 100:
                session = PART_SESSIONS[user_id]
                await process_parts(update, context, session["file_id"], num_parts)
                return
            else:
                await update.message.reply_text(
                    f"{E.ERROR} Please enter a number between 2 and 100.",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                return
        else:
            await update.message.reply_text(
                f"{E.ERROR} Please enter a valid number.",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
            return


    if user_id in SPLIT_SESSIONS:
        if text.isdigit():
            lines_per_file = int(text)
            if lines_per_file >= 10:
                session = SPLIT_SESSIONS[user_id]
                await process_split(update, context, session["file_id"], lines_per_file)
                return
            else:
                await update.message.reply_text(
                    f"{E.ERROR} Please enter at least 10 lines per file.",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                return
        else:
            await update.message.reply_text(
                f"{E.ERROR} Please enter a valid number.",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
            return






@check_lock
@rate_limit("gate")
async def txt_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help for txt commands."""
    await update.message.reply_text(
        f"""
{E.FILE} <b>File Commands</b>
━━━━━━━━━━━━━━━━━━
{E.FILE} <code>/merge</code> - Merge multiple files
└─ Send files one by one (max 20 MB each), type <code>/done</code> to finish

{E.FILE} <code>/split 500</code> - Split by lines
└─ Reply to a .txt file (max 20 MB) or I'll ask how many lines

{E.FILE} <code>/parts 5</code> - Split into N parts
└─ Reply to a .txt file (max 20 MB) or I'll ask how many parts

{E.APPROVED} <code>/clean</code> - Extract & clean cards
└─ Reply to a .txt file (max 20 MB) or text message (only for CC)

{E.REFRESH} <code>/shuffle</code> - Shuffle lines
└─ Reply to a .txt file (max 20 MB) or text message (any text)

{E.CLOSE} <code>/cancel</code> - Cancel merge session
{E.SUCCESS} <code>/done</code> - Finish merge session

━━━━━━━━━━━━━━━━━━
<b>Examples:</b>
<code>/split 500</code> - 500 lines per file
<code>/parts 3</code> - Split into 3 equal parts
<code>/merge</code> - Start merge session

<b>File Size Limit:</b> 20 MB per file

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )






def register_txt(app):
    """Register txt command handlers."""
    app.add_handler(CommandHandler("txt", txt_help_command))
    app.add_handler(CommandHandler("merge", merge_command))
    app.add_handler(CommandHandler("split", split_command))
    app.add_handler(CommandHandler("parts", parts_command))
    app.add_handler(CommandHandler("clean", clean_command))
    app.add_handler(CommandHandler("shuffle", shuffle_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_merge_file))
    logger.info("✅ File commands registered (merge, split, parts, clean, shuffle, done, cancel)")