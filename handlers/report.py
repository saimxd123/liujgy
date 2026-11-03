

from datetime import datetime
from pathlib import Path
from telegram import Update, LinkPreviewOptions
from telegram.ext import Application, CommandHandler, ContextTypes

from logger import get_logger
from database.db import (
    get_all_users,
    get_total_users,
    get_total_premium,
    get_total_admins,
    get_total_proxies,
    get_total_sites,
)
from ui.emojis import PremiumEmoji as E
from utils.decorators import admin_only, log_command
from utils.lock_check import check_lock
from config import OWNER_USERNAME, OWNER_NAME

logger = get_logger(__name__)

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)


@check_lock
@admin_only
@log_command
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        f"""
{E.REPORT} ⌠ 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙄𝙉𝙂 𝙍𝙀𝙋𝙊𝙍𝙏𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} Generating reports...
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    try:
        stats_path = REPORT_DIR / f"statistics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(stats_path, "w", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write("BOT STATISTICS REPORT\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Generated : {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
            f.write(f"Users      : {get_total_users()}\n")
            f.write(f"Premium    : {get_total_premium()}\n")
            f.write(f"Admins     : {get_total_admins()}\n")
            f.write(f"Proxies    : {get_total_proxies()}\n")
            f.write(f"Sites      : {get_total_sites()}\n")
            f.write("\nDatabase   : Online\n")
            f.write("Bot        : Running\n")

        users_path = REPORT_DIR / f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        users = get_all_users()
        with open(users_path, "w", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write("USERS REPORT\n")
            f.write("=" * 50 + "\n\n")
            for i, user in enumerate(users, start=1):
                if hasattr(user, 'keys'):
                    user = dict(user)
                premium = "Yes" if user.get("premium_until") else "No"
                banned = "Yes" if user.get("banned") else "No"
                f.write(f"#{i}\n")
                f.write(f"ID        : {user.get('user_id', 'Unknown')}\n")
                f.write(f"Name      : {user.get('first_name', 'Unknown')}\n")
                f.write(f"Username  : @{user.get('username') or 'None'}\n")
                f.write(f"Premium   : {premium}\n")
                f.write(f"Banned    : {banned}\n")
                f.write(f"Joined    : {user.get('joined_at', 'Unknown')}\n")
                f.write("\n" + "-" * 50 + "\n\n")

        await msg.edit_text(
            f"""
{E.FILE} ⌠ 𝙐𝙋𝙇𝙊𝘼𝘿𝙄𝙉𝙂 𝙍𝙀𝙋𝙊𝙍𝙏𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} Uploading reports...
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )


        with open(stats_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=stats_path.name,
            )
        with open(users_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=users_path.name,
            )

        try:
            await msg.delete()
        except Exception as e:
            logger.warning(f"Could not delete progress message: {e}")

        stats_path.unlink()
        users_path.unlink()

        logger.info(f"Reports sent -> {update.effective_user.id}")

    except Exception as e:
        logger.exception("Report generation failed.")
        try:
            await msg.edit_text(
                f"""
{E.ERROR} ⌠ 𝙁𝘼𝙄𝙇𝙀𝘿 𝙏𝙊 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙀 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception:
            await update.message.reply_text(
                f"""
{E.ERROR} ⌠ 𝙁𝘼𝙄𝙇𝙀𝘿 𝙏𝙊 𝙂𝙀𝙉𝙀𝙍𝘼𝙏𝙀 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)}
━━━━━━━━━━━━━━━━━━
<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )


def register_report(app: Application):
    app.add_handler(CommandHandler("report", report))
    logger.info("Report handler registered.")