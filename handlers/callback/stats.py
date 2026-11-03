

from telegram.constants import ParseMode
from config import OWNER_USERNAME, OWNER_NAME

from database.db import (
    get_total_users,
    get_total_admins,
    get_total_premium,
    get_total_proxies,
    get_total_sites,
    get_total_keys,
    get_total_redeems,
)
from ui.buttons import stats_buttons
from ui.fonts import mono
from ui.emojis import PremiumEmoji as E


async def statistics_page(query):
    users = get_total_users()
    admins = get_total_admins()
    premium = get_total_premium()
    proxies = get_total_proxies()
    sites = get_total_sites()
    keys = get_total_keys()
    redeems = get_total_redeems()

    text = f"""
<pre><a href='https://t.me/oggyproo'>⩙</a> <b>{mono("STATISTICS")}</b></pre>

<a href='https://t.me/oggyproo'>⊀</a> <b>👥 𝐔𝐬𝐞𝐫𝐬</b> ↬ <code>{users}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>👑 𝐏𝐫𝐞𝐦𝐢𝐮𝐦</b> ↬ <code>{premium}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>🛡 𝐀𝐝𝐦𝐢𝐧𝐬</b> ↬ <code>{admins}</code>

<a href='https://t.me/oggyproo'>⊀</a> <b>🔑 𝐊𝐞𝐲𝐬</b> ↬ <code>{keys}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>♻ 𝐑𝐞𝐝𝐞𝐞𝐦𝐞𝐝</b> ↬ <code>{redeems}</code>

<a href='https://t.me/oggyproo'>⊀</a> <b>🌐 𝐏𝐫𝐨𝐱𝐢𝐞𝐬</b> ↬ <code>{proxies}</code>
<a href='https://t.me/oggyproo'>⊀</a> <b>🌍 𝐒𝐢𝐭𝐞𝐬</b> ↬ <code>{sites}</code>

<a href='https://t.me/oggyproo'>⊀</a> <b>💾 𝐃𝐚𝐭𝐚𝐛𝐚𝐬𝐞</b> ↬ {E.SUCCESS} Online
<a href='https://t.me/oggyproo'>⊀</a> <b>🟢 𝐁𝐨𝐭</b> ↬ {E.SUCCESS} Running

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await query.edit_message_caption(
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=stats_buttons(),
    )