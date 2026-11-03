

from telegram.constants import ParseMode
from config import OWNER_USERNAME, OWNER_NAME

from database.db import get_total_premium, get_premium_users
from ui.buttons import premium_buttons
from ui.fonts import mono


async def premium_page(query):
    users = get_premium_users()
    total = get_total_premium()

    text = f"""
<pre><a href='https://t.me/oggyproo'>⩙</a> <b>{mono("PREMIUM USERS")}</b></pre>

<a href='https://t.me/oggyproo'>⊀</a> <b>𝐓𝐨𝐭𝐚𝐥</b> ↬ <code>{total}</code>

"""

    if not users:
        text += "\nNo premium users."
    else:
        for user in users[:10]:
            text += f"\n• {user['first_name']}\n<code>{user['user_id']}</code>\n"

    text += f"""

<a href='https://t.me/oggyproo'>⌬</a> <b>𝐃𝐞𝐯</b> ➠ <a href='https://t.me/{OWNER_USERNAME}'>{OWNER_NAME}</a>"""

    await query.edit_message_caption(
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=premium_buttons(),
    )