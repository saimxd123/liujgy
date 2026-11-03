



import time
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest

from gates.msh import (
    export_cards,
    stop_mass_session,
    active_mass_checks,
)

from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME
from core.callbacks import Callback
from database.db import (
    get_user,
    is_admin,
    is_premium,
    is_banned,
    ban_user,
    unban_user,
    add_admin,
    remove_admin,
    set_premium,
    remove_premium,
    get_premium_users,
    get_total_premium,
    get_total_users,
    get_total_admins,
    get_total_banned,
    get_total_proxies,
    get_all_sites,
    get_all_working_sites,
    is_bot_locked,
)

from ui.buttons import (
    admin_panel_buttons,
    user_profile_buttons,
    back_close_buttons,
    users_buttons,
    users_advanced_buttons,
    gates_toggle_buttons,
)

from ui.pages import (
    home_page,
    profile_page,
    commands_page,
    settings_page,
    help_page,
    pricing_page,
    admin_panel,
    render_page,
)

from handlers.stats import build_statistics
from handlers.callback.admin import ADMIN_CALLBACKS
from handlers.callback.pages import PAGE_CALLBACKS
from handlers.callback.users import users_page, user_profile_page

from handlers.broad import broadcast_notification_callback
from handlers.admin import admin_page_callback

from logger import get_logger
from ui.emojis import PremiumEmoji as E
from ui.emojis import ButtonEmoji as BE
from utils.html_utils import sanitize_html


logger = get_logger(__name__)






PAGE_HANDLERS = {
    Callback.HOME: home_page,
    Callback.PROFILE: profile_page,
    Callback.COMMANDS: commands_page,
    Callback.SETTINGS: settings_page,
    Callback.HELP: help_page,
    Callback.PRICING: pricing_page,
}






async def handle_check_joined(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'I have joined' button callback."""
    try:
        from forcejoin import check_joined_callback
        await check_joined_callback(update, context)
    except ImportError as e:
        logger.error(f"Failed to import check_joined_callback: {e}")






async def speed_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle speed callback queries."""
    try:
        from handlers.speed import speed_callback
        await speed_callback(update, context)
    except ImportError as e:
        logger.error(f"Failed to import speed_callback: {e}")






async def handle_msh_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle MSH export callbacks."""
    query = update.callback_query
    data = query.data

    try:
        parts = data.split("_")

        if len(parts) >= 4:
            card_type = parts[2]
            session_id = "_".join(parts[3:])



            await export_cards(query, session_id, card_type)

    except ImportError as e:
        logger.error(f"Failed to import msh export: {e}")

    except Exception as e:
        logger.error(f"MSH export callback error: {e}")


async def handle_msh_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle MSH stop callbacks."""
    query = update.callback_query
    data = query.data

    try:
        session_id = data.replace("msh_stop_", "")


        await stop_mass_session(query, session_id)

    except ImportError as e:
        logger.error(f"Failed to import msh stop: {e}")

    except Exception as e:
        logger.error(f"MSH stop callback error: {e}")


async def handle_msh_recheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle MSH recheck callbacks."""
    query = update.callback_query
    data = query.data

    try:
        from gates.msh import recheck_error_cards

        session_id = data.replace("msh_recheck_", "")

        await recheck_error_cards(query, session_id)

    except ImportError as e:
        logger.error(f"Failed to import msh recheck: {e}")

    except Exception as e:
        logger.error(f"MSH recheck callback error: {e}")


async def handle_msh_download_errors(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """Handle MSH download errors callbacks."""
    query = update.callback_query
    data = query.data

    try:
        from gates.msh import download_error_cards

        session_id = data.replace("msh_download_errors_", "")

        await download_error_cards(query, session_id)

    except ImportError as e:
        logger.error(f"Failed to import msh download: {e}")

    except Exception as e:
        logger.error(f"MSH download callback error: {e}")






async def handle_fb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Feedback (FB) callback queries."""
    try:
        from handlers.fb import fb_callback

        await fb_callback(update, context)

    except ImportError as e:
        logger.error(f"Failed to import fb_callback: {e}")







async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data
    user = query.from_user

    logger.info(f"Callback: {user.id} -> {data}")















    self_answering = (
        data.startswith("msh_")
    )

    if not self_answering:
        try:
            await query.answer()
        except Exception as e:
            logger.debug(f"Failed to answer callback: {e}")























    if data.startswith("fb_"):
        await handle_fb_callback(update, context)
        return





    if data.startswith("speed_"):
        await speed_callback_handler(update, context)
        return







    if data.startswith("msh_export_"):
        await handle_msh_export(update, context)
        return

    if data.startswith("msh_stop_"):
        await handle_msh_stop(update, context)
        return

    if data.startswith("msh_recheck_"):
        await handle_msh_recheck(update, context)
        return

    if data.startswith("msh_download_errors_"):
        await handle_msh_download_errors(update, context)
        return







    if data == "check_joined":
        await handle_check_joined(update, context)
        return





    if user.id != OWNER_ID and is_bot_locked():
        try:
            await query.edit_message_text(
                "🔒 Bot is locked. Try again later."
            )
        except Exception:
            pass

        return





    if data.startswith("admin_page:"):
        await admin_page_callback(update, context)
        return





    if data.startswith("cmd_page:"):
        try:
            page = int(data.split(":")[1])

            context.user_data["cmd_page"] = page

            await commands_page(query)

            return

        except (ValueError, IndexError):
            try:
                await query.edit_message_text(
                    "❌ Invalid page."
                )
            except Exception:
                pass

            return





    if data in PAGE_CALLBACKS:
        await PAGE_CALLBACKS[data](query)
        return





    if data in ADMIN_CALLBACKS:
        await ADMIN_CALLBACKS[data](query)
        return





    if data in PAGE_HANDLERS:
        await PAGE_HANDLERS[data](query)
        return

    if data.startswith("users.page:"):
        try:
            page = int(data.split(":")[1])
            await users_page(query, page)
        except (ValueError, IndexError):
            await query.answer("Invalid page.", show_alert=True)
        return

    if data == Callback.ADMIN:
        if user.id != OWNER_ID and not is_admin(user.id):
            try:
                await query.edit_message_text("❌ Admins only.")
            except Exception:
                pass
            return
        await admin_panel(query)
        return

    # ─── Gates toggle panel ───────────────────────────────────────────────────
    if data == "admin_gates":
        if user.id != OWNER_ID and not is_admin(user.id):
            await query.answer("Owner/Admin only.", show_alert=True)
            return
        from database.db import get_gate_status_all
        try:
            statuses = get_gate_status_all()
        except Exception:
            statuses = {}
        try:
            await query.edit_message_caption(
                caption=(
                    f"🔒 <b>Gates Control Panel</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Tap a gate to toggle ON/OFF."
                ),
                parse_mode="HTML",
                reply_markup=gates_toggle_buttons(statuses),
            )
        except Exception:
            await query.edit_message_text(
                text=(
                    f"🔒 <b>Gates Control Panel</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Tap a gate to toggle ON/OFF."
                ),
                parse_mode="HTML",
                reply_markup=gates_toggle_buttons(statuses),
            )
        return

    if data.startswith("gate_toggle:"):
        if user.id != OWNER_ID and not is_admin(user.id):
            await query.answer("Owner/Admin only.", show_alert=True)
            return
        gate_name = data.split(":", 1)[1]
        from database.db import toggle_gate_status, get_gate_status_all
        new_state = toggle_gate_status(gate_name)
        statuses  = get_gate_status_all()
        state_str = "✅ ENABLED" if new_state else "❌ DISABLED"
        await query.answer(f"{gate_name}: {state_str}", show_alert=True)
        try:
            await query.edit_message_reply_markup(
                reply_markup=gates_toggle_buttons(statuses)
            )
        except Exception:
            pass
        return

    # ─── Owner panel from admin panel ─────────────────────────────────────────
    if data == "admin_opanel":
        if user.id != OWNER_ID:
            await query.answer("Owner only.", show_alert=True)
            return
        from handlers.owner_panel import _owner_panel_text, _owner_panel_buttons
        try:
            await query.edit_message_caption(
                caption=_owner_panel_text(),
                parse_mode="HTML",
                reply_markup=_owner_panel_buttons(),
            )
        except Exception:
            await query.edit_message_text(
                text=_owner_panel_text(),
                parse_mode="HTML",
                reply_markup=_owner_panel_buttons(),
            )
        return

    if data == Callback.USERS:
        await users_page(query, 1)
        return

    if data == Callback.STATS:

        try:
            await query.edit_message_caption(
                caption=build_statistics(),
                parse_mode="HTML",
                reply_markup=admin_panel_buttons(),
            )

        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Stats error: {e}")

        return





    if data.startswith(Callback.USER_INFO + ":"):

        try:
            target_id = int(data.split(":")[1])
            target = get_user(target_id)

            if not target:
                try:
                    await query.edit_message_text(
                        "❌ User not found."
                    )
                except Exception:
                    pass

                return

            if hasattr(target, "keys"):
                target = dict(target)

            text = f"""
{E.USERS} <b>User Profile</b>
━━━━━━━━━━━━━━━━━━
{E.EMOJI_3} <b>ID</b> ↬ <code>{target.get('user_id', target_id)}</code>
{E.EMOJI_2} <b>Name</b> ↬ {target.get('first_name', 'Unknown')}
{E.EMOJI_4} <b>Username</b> ↬ @{target.get('username') or 'None'}

{E.STAR} <b>Premium</b> ↬ {E.APPROVED if is_premium(target_id) else E.ERROR}
{E.BAN} <b>Banned</b> ↬ {E.APPROVED if is_banned(target_id) else E.ERROR}
{E.SHIELD} <b>Admin</b> ↬ {E.APPROVED if is_admin(target_id) else E.ERROR}

{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>
"""

            text = sanitize_html(text)

            try:
                await query.edit_message_caption(
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=user_profile_buttons(
                        user_id=target_id,
                        premium=is_premium(target_id),
                        admin=is_admin(target_id),
                        banned=is_banned(target_id),
                    ),
                )

            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(
                        f"User profile error: {e}"
                    )

        except (ValueError, IndexError):
            pass

        return






    if data == "admin_stats_refresh":
        if user.id != OWNER_ID and not is_admin(user.id):
            await query.answer("Admins only.", show_alert=True)
            return
        from handlers.callback.stats import statistics_page
        await statistics_page(query)
        return

    if data == "admin_premium_refresh":
        if user.id != OWNER_ID and not is_admin(user.id):
            await query.answer("Admins only.", show_alert=True)
            return
        from handlers.callback.premium import premium_page
        await premium_page(query)
        return

    if data == Callback.SITES:
        if user.id != OWNER_ID and not is_admin(user.id):
            await query.answer("Admins only.", show_alert=True)
            return
        text = f"""
{E.SITES} ⌠ 𝙎𝙄𝙏𝙀𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} <b>Total Sites</b> ➜ <code>{len(get_all_sites())}</code>
{E.APPROVED} <b>Working</b> ➜ <code>{len(get_all_working_sites())}</code>

Use <code>/getsite</code> to export sites.
Use <code>/ts</code> to test sites.
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        await render_page(query, text, admin_panel_buttons())
        return

    if data == Callback.PROXIES:
        if user.id != OWNER_ID and not is_admin(user.id):
            await query.answer("Admins only.", show_alert=True)
            return
        text = f"""
{E.GLOBE} ⌠ 𝙋𝙍𝙊𝙓𝙄𝙀𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} <b>Total Proxies</b> ➜ <code>{get_total_proxies()}</code>

Use <code>/proxy</code> to manage proxies.
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        await render_page(query, text, admin_panel_buttons())
        return

    if data == Callback.REPORT:
        if user.id != OWNER_ID and not is_admin(user.id):
            await query.answer("Admins only.", show_alert=True)
            return
        text = f"""
{E.INFO} ⌠ 𝙍𝙀𝙋𝙊𝙍𝙏 ⌡
━━━━━━━━━━━━━━━━━━
Use <code>/report</code> to submit a report.
━━━━━━━━━━━━━━━━━━
{E.LINK} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""
        await render_page(query, text, admin_panel_buttons())
        return

    if data.startswith(Callback.USER_BAN + ":"):

        try:
            target_id = int(data.split(":")[1])

            if user.id == target_id:
                try:
                    await query.edit_message_text(
                        "❌ You can't ban yourself."
                    )
                except Exception:
                    pass

                return

            ban_user(target_id)

            await users_page(query, 1)

        except (ValueError, IndexError):
            pass

        return





    if data.startswith(Callback.USER_UNBAN + ":"):

        try:
            target_id = int(data.split(":")[1])

            unban_user(target_id)

            await users_page(query, 1)

        except (ValueError, IndexError):
            pass

        return





    if data.startswith(Callback.USER_ADD_ADMIN + ":"):

        try:
            target_id = int(data.split(":")[1])

            add_admin(target_id, user.id)

            await users_page(query, 1)

        except (ValueError, IndexError):
            pass

        return





    if data.startswith(Callback.USER_REMOVE_ADMIN + ":"):

        try:
            target_id = int(data.split(":")[1])

            if target_id == OWNER_ID:
                try:
                    await query.edit_message_text(
                        "❌ Can't remove owner."
                    )
                except Exception:
                    pass

                return

            remove_admin(target_id)

            await users_page(query, 1)

        except (ValueError, IndexError):
            pass

        return





    if data.startswith(Callback.USER_GIVE_PREMIUM + ":"):

        try:
            target_id = int(data.split(":")[1])

            expires = datetime.now() + timedelta(days=30)
            set_premium(target_id, expires)
            from handlers.premium_notify import schedule_premium_notifications
            schedule_premium_notifications(context.bot, target_id, expires)

            await users_page(query, 1)

        except (ValueError, IndexError):
            pass

        return





    if data.startswith(Callback.USER_REMOVE_PREMIUM + ":"):

        try:
            target_id = int(data.split(":")[1])

            remove_premium(target_id)
            from handlers.premium_notify import cancel_premium_notifications, send_premium_expired_message
            cancel_premium_notifications(target_id)
            await send_premium_expired_message(context.bot, target_id, force=True)

            await users_page(query, 1)

        except (ValueError, IndexError):
            pass

        return





    if data == Callback.CLOSE:

        try:
            await query.message.delete()
        except Exception:
            pass

        return





    if data == "ignore":
        return





    if (
        data.startswith("broad_notify_")
        or data.startswith("broad_stop_")
    ):
        await broadcast_notification_callback(
            update,
            context
        )
        return





    logger.warning(f"Unknown callback: {data}")

    try:
        await query.edit_message_text(
            "❌ Unknown action."
        )
    except Exception:
        pass






def register_callback(app: Application):
    """Register callback query handler."""

    app.add_handler(
        CallbackQueryHandler(callback_router)
    )

    logger.info("✅ Callback handler registered.")