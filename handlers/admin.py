

import time

from telegram import Update, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from config import START_PHOTO, OWNER_ID, OWNER_USERNAME, OWNER_NAME
from logger import get_logger
from database.db import (
    is_admin,
    clear_all_user_proxies,
    clear_all_sites,
    clear_all_premium,
    clear_all_admins,
)
from ui.emojis import PremiumEmoji as E
from ui.emojis import ButtonEmoji as BE
from utils.decorators import admin_only, log_command
from utils.lock_check import check_lock
from gates.session_manager import session_manager

logger = get_logger(__name__)



def _get_all_live_sessions() -> list:
    """Collect active sessions stored directly by MSH."""
    try:
        module=__import__("gates.msh", fromlist=["active_mass_checks"])
        store=getattr(module,"active_mass_checks",{})
        sessions=[]
        if isinstance(store,dict):
            for session_id,data in list(store.items()):
                if not isinstance(data,dict) or data.get("stopped",False) or data.get("completed",False): continue
                item=dict(data); item["session_id"]=item.get("session_id") or session_id; item["session_type"]="MSH"; sessions.append(item)
        return sessions
    except Exception as exc:
        logger.warning(f"Failed to read MSH active sessions: {exc}")
        return []

def _collect_active_sessions() -> list:
    """Return active sessions from all session stores without duplicates."""
    sessions = session_manager.get_all_active_sessions()
    seen = {str(s.get("session_id")) for s in sessions}
    for session in _get_all_live_sessions():
        sid = str(session.get("session_id"))
        if sid not in seen:
            sessions.append(session)
            seen.add(sid)
    return sessions


async def _stop_external_session(session_id: str, reason: str = None):
    try:
        module=__import__("gates.msh", fromlist=["active_mass_checks"])
        store=getattr(module,"active_mass_checks",{})
        session=store.get(session_id) if isinstance(store,dict) else None
        if not isinstance(session,dict): return None
        session["stopped"]=True; session["stop_reason"]=reason or "Stopped by administrator"
        ev=session.get("stop_event")
        if ev is not None:
            try: ev.set()
            except Exception: pass
        for task in list(session.get("workers",[])):
            try:
                if task and not task.done(): task.cancel()
            except Exception: pass
        return dict(session)
    except Exception as exc:
        logger.error(f"Failed to stop MSH session {session_id}: {exc}")
        return None

def get_admin_pages(user_id: int) -> dict:
    """Generate admin command pages."""
    is_owner = user_id == OWNER_ID
    
    page1 = f"""
{E.SHIELD} ⌠ 𝘼𝘿𝙈𝙄𝙉 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎 ⌡ 1/2
━━━━━━━━━━━━━━━━━━

▸ {E.STATS} <b>𝙎𝙩𝙖𝙩𝙨 & 𝙍𝙚𝙥𝙤𝙧𝙩𝙨</b>
/admin   - Show this panel
/stats   - View bot statistics
/report  - Generate reports
/vps     - VPS status
/session - Active sessions

━━━━━━━━━━━━━━━━━━
▸ {E.KEY} <b>𝙆𝙚𝙮𝙨</b>
/genkey  - Generate premium key
/delkey  - Delete a key
/redeem  - Redeem a key (user command)

━━━━━━━━━━━━━━━━━━
▸ {E.GLOBE} <b>𝙋𝙧𝙤𝙭𝙞𝙚𝙨</b>
/proxy   - Add proxy (user command)
/tp      - Test proxies (user/owner)
/getproxy - Export proxies (user)
/rmproxy - Delete proxy (user)
/clearproxy - Clear proxies (user)
/clear all - WIPE EVERYTHING ⚠️

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    page2 = f"""
{E.SHIELD} ⌠ 𝘼𝘿𝙈𝙄𝙉 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎 ⌡ 2/2
━━━━━━━━━━━━━━━━━━

▸ {E.SITES} <b>𝙎𝙞𝙩𝙚𝙨</b> (Admin+)
/addsite  - Add sites
/ts       - Test a single site
/getsite  - Export sites
/rmsite   - Delete site
/clearsites - Clear all sites

━━━━━━━━━━━━━━━━━━
▸ {E.USERS} <b>𝙐𝙨𝙚𝙧𝙨</b> (Admin+)
/ban      - Ban user
/unban    - Unban user
/addadmin - Add admin (Owner)
/rmadmin  - Remove admin (Owner)
/auth     - Give premium
/unauth   - Remove premium

━━━━━━━━━━━━━━━━━━
▸ {E.GEAR} <b>𝙂𝙖𝙩𝙚 𝘾𝙤𝙣𝙩𝙧𝙤𝙡</b> (Owner)
/ongate   - Enable gate
/offgate  - Disable gate
/gatestatus - Gate status
/speed    - Set threads
/lock     - Lock bot
/unlock   - Unlock bot
/broad    - Broadcast message

━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
    
    return {1: page1, 2: page2}


def get_admin_nav_buttons(page: int, total_pages: int = 2) -> InlineKeyboardMarkup:
    """Get colored navigation buttons for admin pages."""
    buttons = []
    
    nav_row = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="Prev",
                callback_data=f"admin_page:{page-1}",
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
                callback_data=f"admin_page:{page+1}",
                style="success",
                icon_custom_emoji_id=BE.VIEW
            )
        )
    buttons.append(nav_row)
    
    buttons.append([
        InlineKeyboardButton(
            text="Home",
            callback_data="page_home",
            style="primary",
            icon_custom_emoji_id=BE.HOME
        ),
        InlineKeyboardButton(
            text="Close",
            callback_data="ignore",
            style="danger",
            icon_custom_emoji_id=BE.CLOSE_EMOJI
        ),
    ])
    
    return InlineKeyboardMarkup(buttons)


@admin_only
@log_command
@check_lock
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin commands panel with navigation."""
    user = update.effective_user
    user_id = user.id
    
    pages = get_admin_pages(user_id)
    text = pages.get(1, pages[1])
    reply_markup = get_admin_nav_buttons(1, 2)

    await update.message.reply_photo(
        photo=START_PHOTO,
        caption=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )

    logger.info(f"/admin -> {user.id}")


async def admin_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin page navigation callback."""
    query = update.callback_query
    try:
        page = int(query.data.split(":")[1])
        user_id = query.from_user.id
        
        pages = get_admin_pages(user_id)
        text = pages.get(page, pages[1])
        reply_markup = get_admin_nav_buttons(page, 2)
        
        await query.edit_message_caption(
            caption=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Admin page callback error: {e}")
        await query.answer(f"{E.ERROR} Error loading page.", show_alert=True)


@admin_only
async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List active sessions from SessionManager and all gate session stores."""
    active_sessions = _collect_active_sessions()

    if not active_sessions:
        await update.message.reply_text(
            f"{E.INFO} No active sessions.",
            parse_mode="HTML"
        )
        return

    text = f"{E.SEARCH} ⌠ 𝘼𝘾𝙏𝙄𝙑𝙀 𝙎𝙀𝙎𝙎𝙄𝙊𝙉𝙎 ⌡\n"
    text += f"━━━━━━━━━━━━━━━━━━\n"
    text += f"Total: {len(active_sessions)}\n\n"

    for i, sess in enumerate(active_sessions, 1):
        session_id = sess.get("session_id", "N/A")
        user_id = sess.get("user_id", "Unknown")
        session_type = sess.get("session_type", "MANAGER")

        created = sess.get("created_at", 0)
        created_str = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created))
            if created else "N/A"
        )

        text += f"#{i}  {E.USER} <b>User:</b> <code>{user_id}</code>\n"
        text += f"   {E.GLOBE} <b>Type:</b> <code>{session_type}</code>\n"
        text += f"   {E.CLOCK} <b>Started:</b> {created_str}\n"
        text += f"   {E.KEY} <b>Session ID:</b> <code>{session_id}</code>\n"

        stats = sess.get("stats", {})
        if isinstance(stats, dict) and stats:
            checked = stats.get("checked", 0)
            total = stats.get("total", 0)
            charged = stats.get("charged", 0)
            text += f"   {E.STATS} Checked: {checked}/{total} | Charged: {charged}\n"
        text += "\n"

    text += f"━━━━━━━━━━━━━━━━━━\n"
    text += f"{E.NOTE} Use /stopsession &lt;session_id&gt; &lt;reason&gt; to stop a session."

    await update.message.reply_text(text, parse_mode="HTML")


@admin_only
async def stopsession_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop an active session from any supported session store."""
    args = context.args
    if not args:
        await update.message.reply_text(
            f"{E.ERROR} Usage: /stopsession <session_id> [reason]",
            parse_mode="HTML"
        )
        return

    session_id = args[0]
    reason = " ".join(args[1:]) if len(args) > 1 else None

    stopped_session = await session_manager.stop_session(session_id, reason)
    if not stopped_session:
        stopped_session = await _stop_external_session(session_id, reason)

    if not stopped_session:
        await update.message.reply_text(
            f"{E.ERROR} Session `{session_id}` not found or already inactive.",
            parse_mode="HTML"
        )
        return

    user_id = stopped_session.get("user_id")

    if user_id:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"""
{E.WARNING} ⌠ 𝙎𝙀𝙎𝙎𝙄𝙊𝙉 𝙎𝙏𝙊𝙋𝙋𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.USER} Your session `{session_id}` has been stopped by an administrator.

{E.NOTE} <b>Reason:</b> {reason or 'No reason provided'}

Please contact support if you have questions.
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
""",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} about session stop: {e}")

    await update.message.reply_text(
        f"""
{E.SUCCESS} ⌠ 𝙎𝙀𝙎𝙎𝙄𝙊𝙉 𝙎𝙏𝙊𝙋𝙋𝙀𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.USER} Session `{session_id}` stopped successfully.
{E.USER} Owner: `{user_id}`
{E.NOTE} Reason: {reason or 'No reason provided'}
━━━━━━━━━━━━━━━━━━
""",
        parse_mode="HTML"
    )


async def vps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed VPS status (Admin only)."""
    if not is_admin(update.effective_user.id) and update.effective_user.id != OWNER_ID:
        await update.message.reply_text(f"{E.ERROR} Admin only.", parse_mode="HTML")
        return

    try:
        import psutil
        import platform
        import socket
        from datetime import datetime
        import os
        import sys

        hostname = socket.gethostname()
        system = platform.system()
        release = platform.release()
        version = platform.version()
        architecture = platform.machine()
        python_version = sys.version.split()[0]
        
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_text = f"{cpu_freq.current:.0f}MHz" if cpu_freq else "N/A"
        
        memory = psutil.virtual_memory()
        memory_total_gb = memory.total / (1024**3)
        memory_used_gb = memory.used / (1024**3)
        memory_available_gb = memory.available / (1024**3)
        memory_percent = memory.percent
        
        swap = psutil.swap_memory()
        swap_total_gb = swap.total / (1024**3)
        swap_used_gb = swap.used / (1024**3)
        swap_percent = swap.percent
        
        disk = psutil.disk_usage('/')
        disk_total_gb = disk.total / (1024**3)
        disk_used_gb = disk.used / (1024**3)
        disk_free_gb = disk.free / (1024**3)
        disk_percent = disk.percent
        
        net_io = psutil.net_io_counters()
        net_sent_gb = net_io.bytes_sent / (1024**3)
        net_recv_gb = net_io.bytes_recv / (1024**3)
        net_packets_sent = net_io.packets_sent
        net_packets_recv = net_io.packets_recv
        
        process_count = len(psutil.pids())
        
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        uptime_days = uptime.days
        uptime_hours = uptime.seconds // 3600
        uptime_minutes = (uptime.seconds % 3600) // 60
        uptime_text = f"{uptime_days}d {uptime_hours}h {uptime_minutes}m"
        
        try:
            from main import BOT_START_TIME
            bot_uptime = datetime.now() - BOT_START_TIME
            bot_uptime_days = bot_uptime.days
            bot_uptime_hours = bot_uptime.seconds // 3600
            bot_uptime_minutes = (bot_uptime.seconds % 3600) // 60
            bot_uptime_text = f"{bot_uptime_days}d {bot_uptime_hours}h {bot_uptime_minutes}m"
        except:
            bot_uptime_text = "N/A"
        
        load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else None
        load_text = f"{load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}" if load_avg else "N/A"
        
        temp_text = "N/A"
        if hasattr(psutil, 'sensors_temperatures'):
            temps = psutil.sensors_temperatures()
            if temps and 'coretemp' in temps:
                core_temps = temps['coretemp']
                if core_temps:
                    temp_text = f"{core_temps[0].current}°C"
        
        text = f"""
{E.GEAR} ⌠ 𝙑𝙋𝙎 𝘿𝙀𝙏𝘼𝙄𝙇𝙀𝘿 𝙎𝙏𝘼𝙏𝙐𝙎 ⌡
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<blockquote><b>{E.INFO} 𝙎𝙔𝙎𝙏𝙀𝙈</b></blockquote>
{E.USER} <b>Hostname</b>   ↬ <code>{hostname}</code>
{E.INFO} <b>OS</b>          ↬ {system} {release}
{E.INFO} <b>Arch</b>        ↬ {architecture}
{E.INFO} <b>Python</b>      ↬ v{python_version}
{E.CLOCK} <b>Uptime</b>      ↬ {uptime_text}

<blockquote><b>{E.THUNDER} 𝘾𝙋𝙐</b></blockquote>
{E.INFO} <b>Usage</b>       ↬ {cpu_percent}%
{E.INFO} <b>Cores</b>        ↬ {cpu_count} Physical ({cpu_count_logical} Logical)
{E.INFO} <b>Frequency</b>    ↬ {cpu_freq_text}
{E.INFO} <b>Load Avg</b>     ↬ {load_text}

<blockquote><b>{E.DATABASE} 𝙈𝙀𝙈𝙊𝙍𝙔</b></blockquote>
{E.INFO} <b>RAM</b>          ↬ {memory_percent}% ({memory_used_gb:.1f}GB / {memory_total_gb:.1f}GB)
{E.INFO} <b>Available</b>    ↬ {memory_available_gb:.1f}GB
{E.INFO} <b>Swap</b>         ↬ {swap_percent}% ({swap_used_gb:.1f}GB / {swap_total_gb:.1f}GB)

<blockquote><b>{E.FILE} 𝘿𝙄𝙎𝙆</b></blockquote>
{E.INFO} <b>Root</b>         ↬ {disk_percent}% ({disk_used_gb:.1f}GB / {disk_total_gb:.1f}GB)
{E.INFO} <b>Free</b>         ↬ {disk_free_gb:.1f}GB

<blockquote><b>{E.GLOBE} 𝙉𝙀𝙏𝙒𝙊𝙍𝙆</b></blockquote>
{E.INFO} <b>Sent</b>        ↬ {net_sent_gb:.2f}GB
{E.INFO} <b>Received</b>    ↬ {net_recv_gb:.2f}GB
{E.INFO} <b>Packets</b>     ↬ {net_packets_sent:,} sent / {net_packets_recv:,} recv

<blockquote><b>{E.HOME} 𝘽𝙊𝙏</b></blockquote>
{E.INFO} <b>Uptime</b>       ↬ {bot_uptime_text}
{E.INFO} <b>Processes</b>    ↬ {process_count}

<blockquote><b>{E.STATS} 𝙎𝙔𝙎𝙏𝙀𝙈 𝙃𝙀𝘼𝙇𝙏𝙃</b></blockquote>
{E.INFO} <b>Temp</b>         ↬ {temp_text}
{E.INFO} <b>Status</b>       ↬ {'🟢 Healthy' if cpu_percent < 80 and memory_percent < 80 and disk_percent < 85 else '🟡 Warning'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        
    except ImportError:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙈𝙄𝙎𝙎𝙄𝙉𝙂 𝘿𝙀𝙋𝙀𝙉𝘿𝙀𝙉𝘾𝙔 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} Please install psutil:
<code>pip install psutil</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"""
{E.ERROR} ⌠ 𝙁𝘼𝙄𝙇𝙀𝘿 𝙏𝙊 𝙁𝙀𝙏𝘾𝙃 ⌡
━━━━━━━━━━━━━━━━━━
{E.NOTE} {str(e)}
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )







async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear admin data with explicit confirmation."""
    user_id = update.effective_user.id
    args = [x.lower().strip() for x in (context.args or [])]

    if not args or args[0] not in {"proxy", "site", "premium", "admin", "all"}:
        await update.message.reply_text(
            f"{E.INFO} <b>Usage:</b>\n"
            f"<code>/clear proxy</code>\n"
            f"<code>/clear site</code>\n"
            f"<code>/clear premium</code>\n"
            f"<code>/clear admin</code>\n"
            f"<code>/clear all</code>",
            parse_mode="HTML",
        )
        return

    target = args[0]



    if target == "all":
        allowed = user_id == OWNER_ID
    else:
        allowed = user_id == OWNER_ID or is_admin(user_id)

    if not allowed:
        await update.message.reply_text(
            f"{E.ERROR} <b>Permission denied.</b>",
            parse_mode="HTML",
        )
        return

    labels = {
        "proxy": "ALL user proxies",
        "site": "ALL sites",
        "premium": "premium status for ALL users",
        "admin": "ALL database admins",
        "all": "proxies, sites, premium status and admins",
    }

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text="Yes, clear",
            callback_data=f"clear_confirm:{target}:{user_id}",
            style="danger",
        ),
        InlineKeyboardButton(
            text="No",
            callback_data=f"clear_cancel:{user_id}",
            style="primary",
        ),
    ]])

    await update.message.reply_text(
        f"{E.WARNING} <b>Confirm /clear {target}</b>\n\n"
        f"⚠️ This action cannot be undone.\n\nThis will permanently remove <b>{labels[target]}</b>.\n\n"
        f"Continue?",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear confirmation buttons."""
    query = update.callback_query
    parts = query.data.split(":")

    try:
        if len(parts) < 3:
            await query.answer("Invalid request.", show_alert=True)
            return

        action = parts[1]
        confirmed_for = int(parts[-1])

        if query.from_user.id != confirmed_for:
            await query.answer("This confirmation isn't yours.", show_alert=True)
            return

        if action == "cancel":
            await query.edit_message_text(
                f"{E.INFO} Clear operation cancelled.",
                parse_mode="HTML",
            )
            await query.answer()
            return

        target = action

        if target in {"admin", "all"}:
            allowed = query.from_user.id == OWNER_ID
        else:
            allowed = query.from_user.id == OWNER_ID or is_admin(query.from_user.id)

        if not allowed:
            await query.answer("Permission denied.", show_alert=True)
            return

        if target == "proxy":
            count = clear_all_user_proxies()
            result = f"Removed <code>{count}</code> user proxies."

        elif target == "site":
            count = clear_all_sites()
            result = f"Removed <code>{count}</code> sites."

        elif target == "premium":
            count = clear_all_premium()
            result = f"Removed premium status from <code>{count}</code> users."

        elif target == "admin":
            count = clear_all_admins()
            result = f"Removed <code>{count}</code> database admins."

        elif target == "all":
            proxy_count = clear_all_user_proxies()
            site_count = clear_all_sites()
            premium_count = clear_all_premium()
            admin_count = clear_all_admins()
            result = (
                f"Proxies: <code>{proxy_count}</code>\n"
                f"Sites: <code>{site_count}</code>\n"
                f"Premium users: <code>{premium_count}</code>\n"
                f"Admins: <code>{admin_count}</code>"
            )

        else:
            await query.answer("Unknown clear option.", show_alert=True)
            return

        logger.warning(
            "CLEAR executed: target=%s user_id=%s",
            target,
            query.from_user.id,
        )

        await query.edit_message_text(
            f"{E.SUCCESS} <b>/clear {target} completed.</b>\n\n{result}",
            parse_mode="HTML",
        )
        await query.answer("Done.")

    except Exception as e:
        logger.exception("Clear command failed: %s", e)
        await query.answer("Clear failed. Check logs.", show_alert=True)


def register_admin(app: Application):
    """Register admin command handlers."""
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("session", session_command))
    app.add_handler(CommandHandler("stopsession", stopsession_command))
    app.add_handler(CommandHandler("vps", vps_command))

    app.add_handler(CallbackQueryHandler(admin_page_callback, pattern="^admin_page:"))
    app.add_handler(CallbackQueryHandler(clear_callback, pattern=r"^clear_(confirm|cancel):"))
    logger.info("✅ Admin handlers registered.")