

from datetime import datetime, timedelta
import asyncio
from telegram import Update, LinkPreviewOptions
from telegram.ext import Application, CommandHandler, ContextTypes
from config import OWNER_USERNAME, OWNER_NAME, OWNER_ID

from logger import get_logger
from database.db import (
    get_total_users,
    get_total_admins,
    get_total_premium,
    get_total_proxies,
    get_total_sites,
    get_user_activity_24h,
    get_user_all_time_stats,
    get_user,
    get_premium_until,
    _get_pool,
    _run_sync,
)
from ui.buttons import stats_buttons
from ui.emojis import PremiumEmoji as E
from utils.decorators import admin_only, log_command, not_banned
from utils.lock_check import check_lock
from plans import get_user_current_tier

logger = get_logger(__name__)






def build_statistics() -> str:
    """Build bot statistics for /bot command."""
    users = get_total_users()
    admins = get_total_admins()
    premium = get_total_premium()
    proxies = get_total_proxies()
    sites = get_total_sites()

    return f"""
{E.STATS} ⌠ 𝘽𝙊𝙏 𝙎𝙏𝘼𝙏𝙄𝙎𝙏𝙄𝘾𝙎 ⌡
━━━━━━━━━━━━━━━━━━
{E.USERS} <b>Users</b>       ↬ <code>{users}</code>
{E.STAR} <b>Premium</b>     ↬ <code>{premium}</code>
{E.SHIELD} <b>Admins</b>      ↬ <code>{admins}</code>


{E.GLOBE} <b>Proxies</b>     ↬ <code>{proxies}</code>
{E.SITES} <b>Sites</b>       ↬ <code>{sites}</code>

{E.DATABASE} <b>Database</b>    ↬ {E.SUCCESS} Online
{E.HOME} <b>Bot</b>         ↬ {E.SUCCESS} Running
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""


@admin_only
@log_command
@check_lock
async def bot_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics (admin only)."""
    user = update.effective_user

    await update.message.reply_text(
        build_statistics(),
        parse_mode="HTML",
        reply_markup=stats_buttons(),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

    logger.info(f"/bot -> {user.id}")






def get_charge_leaderboard(limit: int = 10) -> list:
    """Get top users by recorded charge count (all-time).

    A charge is counted from check_history regardless of gateway name.  Status
    matching is case-insensitive so values such as Charged/charged/CHARGED are
    treated identically.
    """

    async def _query():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    ch.user_id,
                    COUNT(*) AS count,
                    u.first_name,
                    u.username
                FROM check_history ch
                LEFT JOIN users u
                    ON u.user_id = ch.user_id
                WHERE LOWER(TRIM(COALESCE(ch.status, ''))) IN
                      ('charged', 'charge', 'order_paid', 'paid')
                GROUP BY ch.user_id, u.first_name, u.username
                ORDER BY COUNT(*) DESC, ch.user_id ASC
                LIMIT $1
                """,
                limit,
            )
            return rows

    try:
        return [dict(row) for row in _run_sync(_query())]
    except Exception as e:
        logger.error(f"Leaderboard error: {e}", exc_info=True)
        return []


def get_total_charges_all_time() -> int:
    """Get total recorded charges (all-time)."""

    async def _query():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM check_history
                WHERE LOWER(TRIM(COALESCE(status, ''))) IN
                      ('charged', 'charge', 'order_paid', 'paid')
                """
            )

    try:
        return int(_run_sync(_query()) or 0)
    except Exception as e:
        logger.error(f"Total charges error: {e}", exc_info=True)
        return 0


def get_user_charge_rank(user_id: int) -> int:
    """Get user's rank based on all-time charge count."""

    async def _query():
        pool = await _get_pool()
        async with pool.acquire() as conn:

            return await conn.fetchval(
                """
                SELECT COUNT(*) + 1
                FROM (
                    SELECT user_id, COUNT(*) AS count
                    FROM check_history
                    WHERE LOWER(TRIM(COALESCE(status, ''))) IN
                          ('charged', 'charge', 'order_paid', 'paid')
                    GROUP BY user_id
                    HAVING COUNT(*) > (
                        SELECT COUNT(*)
                        FROM check_history
                        WHERE user_id = $1
                          AND LOWER(TRIM(COALESCE(status, ''))) IN
                              ('charged', 'charge', 'order_paid', 'paid')
                    )
                ) AS ranked
                """,
                user_id,
            )

    try:
        return int(_run_sync(_query()) or 0)
    except Exception as e:
        logger.error(f"Rank error: {e}", exc_info=True)
        return 0


@not_banned
@check_lock
async def stats_leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show top 10 users by Shopify charges (all-time)."""
    user = update.effective_user


    leaders = get_charge_leaderboard(10)
    total_charges = get_total_charges_all_time()


    user_rank = get_user_charge_rank(user.id)
    user_charges = get_user_all_time_stats(user.id).get('charged', 0)

    if not leaders:
        await update.message.reply_text(
            f"""
{E.REPORT} ⌠ 𝙇𝙀𝘼𝘿𝙀𝙍𝘽𝙊𝘼𝙍𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.INFO} No charges recorded yet.

Start checking cards to appear on the leaderboard!
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>""",
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        return


    text = f"""
{E.FIRE} ⌠ 𝙇𝙀𝘼𝘿𝙀𝙍𝘽𝙊𝘼𝙍𝘿 ⌡
━━━━━━━━━━━━━━━━━━
{E.CROWN} <b>Top 10 Shopify Hitters (All-Time)</b>
━━━━━━━━━━━━━━━━━━
"""

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for i, leader in enumerate(leaders):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        user_id = leader.get('user_id', 'Unknown')
        count = leader.get('count', 0)
        first_name = leader.get('first_name', 'Unknown')
        username = leader.get('username', '')

        if username:
            display = f"@{username}"
        else:
            display = first_name

        text += f"{medal} <b>{display}</b> ↬ <code>{count}</code> {E.get_charge_emoji()}\n"


    if user_charges > 0 and user_rank > 0:
        text += f"""
━━━━━━━━━━━━━━━━━━
👤 <b>Your Rank:</b> #{user_rank}
{E.get_charge_emoji()} <b>Your Charges:</b> <code>{user_charges}</code>"""

    text += f"""
━━━━━━━━━━━━━━━━━━
{E.CARD} <b>Total Charges:</b> <code>{total_charges}</code>
━━━━━━━━━━━━━━━━━━
{E.DEV} <b>Dev</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )






@not_banned
@check_lock
async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's all-time stats in a clean format."""
    user = update.effective_user
    user_id = user.id


    all_time = get_user_all_time_stats(user_id)
    total_all = all_time.get('total', 0)
    charged_all = all_time.get('charged', 0)
    approved_all = all_time.get('approved', 0)
    declined_all = all_time.get('declined', 0)


    user_rank = get_user_charge_rank(user_id)

    text = f"""
{E.USERS} Your Stats {E.STAR}
────────────
{E.CARD} Total Checked ➳ <code>{total_all:,}</code>
{E.get_charge_emoji()} Total Charged ➳ <code>{charged_all:,}</code>
{E.APPROVED} Total Live ➳ <code>{approved_all:,}</code>
{E.DECLINED} Total Dead ➳ <code>{declined_all:,}</code>
{f"👑 Rank ➳ #{user_rank}" if user_rank > 0 else ""}
────────────
{E.DEV} Dev ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )






def register_stats(app: Application):
    app.add_handler(CommandHandler("bot", bot_stats_command))
    app.add_handler(CommandHandler("stats", stats_leaderboard_command))
    app.add_handler(CommandHandler("me", me_command))
    app.add_handler(CommandHandler("leaderboard", stats_leaderboard_command))
    app.add_handler(CommandHandler("top", stats_leaderboard_command))
    logger.info("✅ Stats handlers registered.")