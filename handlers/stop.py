

import logging
import time

from telegram import Update
from telegram.ext import CallbackContext


from gates.msh import active_mass_checks as msh_active_checks
from gates.mau import active_mass_checks as mau_active_mass_checks

logger = logging.getLogger(__name__)


async def handle_stop_command(update: Update, context: CallbackContext):
    """
    Handle /stop command to stop a specific mass check session.
    """
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name

    if not context.args:

        user_sessions = []

        for session_id, data in msh_active_checks.items():
            if data.get("user_id") == user_id:
                user_sessions.append(("MSH", session_id))

        for session_id, data in mau_active_mass_checks.items():
            if data.get("user_id") == user_id:
                user_sessions.append(("MAU", session_id))

        if not user_sessions:
            await update.message.reply_text(
                "⚠️ <b>No active mass check sessions found.</b>\n\n"
                "Start a mass check with /msh or /mau first.",
                parse_mode="HTML"
            )
            return

        session_list = "\n".join([f"• <code>{module} {session_id}</code>" for module, session_id in user_sessions])
        await update.message.reply_text(
            f"📋 <b>Your active mass check sessions:</b>\n\n"
            f"{session_list}\n\n"
            f"Use /stop &lt;session_id&gt; to stop a specific session.",
            parse_mode="HTML"
        )
        return

    session_id = context.args[0].upper()


    if session_id in msh_active_checks:
        if msh_active_checks[session_id].get("user_id") != user_id:
            await update.message.reply_text("⛔ Access denied! You can only stop your own sessions.", parse_mode="HTML")
            return

        msh_active_checks[session_id]["stopped"] = True
        stop_event = msh_active_checks[session_id].get("stop_event")
        if stop_event:
            stop_event.set()


        for task in msh_active_checks[session_id].get("workers", []):
            if not task.done():
                task.cancel()

        await update.message.reply_text(
            f"✅ <b>MSH session stopped successfully!</b>\n\n"
            f"Session ID: <code>{session_id}</code>",
            parse_mode="HTML"
        )
        return


    if session_id in mau_active_mass_checks:
        if mau_active_mass_checks[session_id].get("user_id") != user_id:
            await update.message.reply_text("⛔ Access denied! You can only stop your own sessions.", parse_mode="HTML")
            return

        mau_active_mass_checks[session_id]["stopped"] = True
        stop_event = mau_active_mass_checks[session_id].get("stop_event")
        if stop_event:
            stop_event.set()

        for task in mau_active_mass_checks[session_id].get("workers", []):
            if not task.done():
                task.cancel()

        await update.message.reply_text(
            f"✅ <b>MAU session stopped successfully!</b>\n\n"
            f"Session ID: <code>{session_id}</code>",
            parse_mode="HTML"
        )
        return

    await update.message.reply_text(
        f"⚠️ <b>No active mass check session found with ID:</b> <code>{session_id}</code>",
        parse_mode="HTML"
    )