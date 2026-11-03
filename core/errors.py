

import traceback
import io
from datetime import datetime
from telegram import Update, LinkPreviewOptions
from telegram.ext import ContextTypes

from logger import get_logger
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from ui.emojis import PremiumEmoji as E

logger = get_logger(__name__)


def get_last_logs(lines: int = 200) -> str:
    """Get the last N lines from the bot log file."""
    try:
        log_file = "logs/bot.log"
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return ''.join(last_lines)
    except Exception as e:
        return f"Failed to read logs: {e}"


def format_traceback(error) -> str:
    """Format the error traceback with truncation."""
    full_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))

    if len(full_traceback) > 1500:
        full_traceback = full_traceback[:1500] + "\n... (truncated)"
    return full_traceback


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler for all unhandled exceptions."""
    logger.exception("Unhandled exception occurred.", exc_info=context.error)

    error_msg = str(context.error)

    if len(error_msg) > 300:
        error_msg = error_msg[:300] + "... (truncated)"
    
    traceback_text = format_traceback(context.error)
    

    last_logs = get_last_logs(200)

    if len(last_logs) > 4000:
        last_logs = last_logs[-4000:] + "\n... (truncated)"

    try:
        user_info = "Unknown"
        chat_info = "Unknown"
        message_text = "None"
        
        if isinstance(update, Update):
            if update.effective_user:
                user_info = f"{update.effective_user.id} (@{update.effective_user.username})"
            if update.effective_chat:
                chat_info = update.effective_chat.id
            if update.effective_message:
                message_text = update.effective_message.text or "No text"

                if len(message_text) > 200:
                    message_text = message_text[:200] + "... (truncated)"

        logger.error(
            "\n========== ERROR ==========\n"
            f"User      : {user_info}\n"
            f"Chat      : {chat_info}\n"
            f"Text      : {message_text}\n"
            f"Exception : {error_msg}\n"
            "===========================\n"
        )




        try:
            bot = context.bot
            
            error_report = f"""
{E.ERROR} ⌠ 𝙀𝙍𝙍𝙊𝙍 𝘿𝙀𝙏𝙀𝘾𝙏𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} <b>User</b>  : <code>{user_info}</code>
{E.INFO} <b>Chat</b>   : <code>{chat_info}</code>
{E.INFO} <b>Command</b>: <code>{message_text}</code>
{E.INFO} <b>Time</b>   : <code>{datetime.now().strftime('%d %b %Y %H:%M:%S')}</code>

<b>Error:</b>
<code>{error_msg}</code>
━━━━━━━━━━━━━━━━━━
📁 Logs will be sent in the next message
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

            await bot.send_message(
                chat_id=OWNER_ID,
                text=error_report,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )

            logger.info(f"Error report sent to owner for user {user_info}")

        except Exception as e:
            logger.error(f"Failed to send error report to owner: {e}")




        try:
            bot = context.bot

            logs_text = f"""
📋 ⌠ 𝙀𝙍𝙍𝙊𝙍 𝙇𝙊𝙂𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} <b>User</b>  : <code>{user_info}</code>
{E.INFO} <b>Time</b>   : <code>{datetime.now().strftime('%d %b %Y %H:%M:%S')}</code>

<pre>
{last_logs}
</pre>
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""


            if len(logs_text) < 4096:
                await bot.send_message(
                    chat_id=OWNER_ID,
                    text=logs_text,
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            else:

                logs_file = io.BytesIO(last_logs.encode('utf-8'))
                logs_file.name = f"error_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

                await bot.send_document(
                    chat_id=OWNER_ID,
                    document=logs_file,
                    caption=f"""
📋 ⌠ 𝙀𝙍𝙍𝙊𝙍 𝙇𝙊𝙂𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} <b>User</b>  : <code>{user_info}</code>
{E.INFO} <b>Time</b>   : <code>{datetime.now().strftime('%d %b %Y %H:%M:%S')}</code>

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                )
                logs_file.close()

            logger.info(f"Error logs sent to owner for user {user_info}")

        except Exception as e:
            logger.error(f"Failed to send error logs to owner: {e}")




        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    f"""
{E.ERROR} ⌠ 𝙀𝙍𝙍𝙊𝙍 𝘿𝙀𝙏𝙀𝘾𝙏𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} An unexpected error occurred.

The developers have been notified.

Please try again later or contact support if the issue persists.
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                    parse_mode="HTML",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            except Exception as e:
                logger.error(f"Failed to send user error message: {e}")

    except Exception as e:
        logger.exception(f"Error in global error handler: {e}")