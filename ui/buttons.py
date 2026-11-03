

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from core.callbacks import Callback
from ui.emojis import ButtonEmoji as BE






def home_buttons(is_admin: bool = False):
    keyboard = [
        [
            InlineKeyboardButton(
                text="Profile",
                callback_data=Callback.PROFILE,
                style="primary",
                icon_custom_emoji_id=BE.PROFILE
            ),
            InlineKeyboardButton(
                text="Commands",
                callback_data=Callback.COMMANDS,
                style="primary",
                icon_custom_emoji_id=BE.SEARCH
            ),
        ],
        [
            InlineKeyboardButton(
                text="Pricing",
                callback_data=Callback.PRICING,
                style="success",
                icon_custom_emoji_id=BE.PRICING
            ),
        ],
        [
            InlineKeyboardButton(
                text="Group",
                url="https://t.me/+Y1hpddJIEPw1ZGVl",
                style="primary",
                icon_custom_emoji_id=BE.GROUP
            ),
            InlineKeyboardButton(
                text="Updates",
                url="https://t.me/oggyproo",
                style="primary",
                icon_custom_emoji_id=BE.UPDATES
            ),
        ],
        [
            InlineKeyboardButton(
                text="Dev",
                url="https://t.me/oggyproo",
                style="primary",
                icon_custom_emoji_id=BE.DEV
            ),
            InlineKeyboardButton(
                text="Support",
                url="https://t.me/oggyproo",
                style="primary",
                icon_custom_emoji_id=BE.SUPPORT
            ),
        ],
    ]

    if is_admin:
        keyboard.append([
            InlineKeyboardButton(
                text="Admin Panel",
                callback_data=Callback.ADMIN,
                style="primary",
                icon_custom_emoji_id=BE.ADMIN
            ),
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="Close",
            callback_data=Callback.CLOSE,
            style="danger",
            icon_custom_emoji_id=BE.CLOSE_EMOJI
        ),
    ])

    return InlineKeyboardMarkup(keyboard)






def profile_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=Callback.HOME,
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI
            ),
            InlineKeyboardButton(
                text="Close",
                callback_data=Callback.CLOSE,
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            ),
        ],
    ])







def pricing_buttons():
    """Pricing navigation with a direct owner contact button."""
    from config import OWNER_USERNAME
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="💳 Buy Premium",
                url=f"https://t.me/{OWNER_USERNAME}",
                style="success",
                icon_custom_emoji_id=BE.PRICING,
            )
        ],
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=Callback.HOME,
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI,
            ),
            InlineKeyboardButton(
                text="Close",
                callback_data=Callback.CLOSE,
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI,
            ),
        ],
    ])


def admin_panel_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(text="Users",  callback_data=Callback.USERS, style="primary", icon_custom_emoji_id=BE.USERS),
            InlineKeyboardButton(text="Stats",  callback_data=Callback.STATS, style="primary", icon_custom_emoji_id=BE.STATS_EMOJI),
        ],
        [
            InlineKeyboardButton(text="Sites",   callback_data=Callback.SITES,   style="success", icon_custom_emoji_id=BE.PREMIUM),
            InlineKeyboardButton(text="Proxies", callback_data=Callback.PROXIES, style="success", icon_custom_emoji_id=BE.SETTINGS_EMOJI),
        ],
        [
            InlineKeyboardButton(text="🔒 Gates",       callback_data="admin_gates",  style="danger",  icon_custom_emoji_id=BE.SETTINGS_EMOJI),
            InlineKeyboardButton(text="⚙️ Owner Panel", callback_data="admin_opanel", style="primary", icon_custom_emoji_id=BE.ADMIN),
        ],
        [
            InlineKeyboardButton(text="Report", callback_data=Callback.REPORT, style="primary", icon_custom_emoji_id=BE.REPORT),
        ],
        [
            InlineKeyboardButton(text="Back",  callback_data=Callback.HOME,  style="primary", icon_custom_emoji_id=BE.BACK_EMOJI),
            InlineKeyboardButton(text="Close", callback_data=Callback.CLOSE, style="danger",  icon_custom_emoji_id=BE.CLOSE_EMOJI),
        ],
    ])


def gates_toggle_buttons(gate_statuses: dict):
    """Gate enable/disable panel with colored buttons."""
    def _btn(label, gate_name, emoji):
        enabled = gate_statuses.get(gate_name, True)
        style   = "success" if enabled else "danger"
        state   = "ON ✅" if enabled else "OFF ❌"
        return InlineKeyboardButton(
            text=f"{emoji} {label} {state}",
            callback_data=f"gate_toggle:{gate_name}",
            style=style,
        )

    return InlineKeyboardMarkup([
        [_btn("Shopify",          "shopify",            "🛍")],
        [_btn("Shopify Mass",     "shopify_mass",       "🛍")],
        [_btn("Stripe Auth",      "stripe_auth",        "✅")],
        [_btn("Stripe Auth Mass", "stripe_auth_mass",   "✅")],
        [_btn("Stripe Auth2 $0",  "stripe_auth2",       "🔐")],
        [_btn("Auth2 Mass",       "stripe_auth2_mass",  "🔐")],
        [_btn("Stripe Charge $5", "stripe_charge",      "💳")],
        [_btn("Charge $5 Mass",   "stripe_charge_mass", "💳")],
        [
            InlineKeyboardButton(text="Back",  callback_data=Callback.ADMIN, style="primary", icon_custom_emoji_id=BE.BACK_EMOJI),
            InlineKeyboardButton(text="Close", callback_data=Callback.CLOSE, style="danger",  icon_custom_emoji_id=BE.CLOSE_EMOJI),
        ],
    ])




def proxy_admin_buttons():
    """Proxy management page - only Back/Close buttons."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=Callback.ADMIN,
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI
            ),
            InlineKeyboardButton(
                text="Close",
                callback_data=Callback.CLOSE,
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            ),
        ],
    ])






def user_profile_buttons(user_id: int, premium: bool, admin: bool, banned: bool):
    keyboard = []

    if premium:
        keyboard.append([
            InlineKeyboardButton(
                text="Remove Premium",
                callback_data=f"{Callback.USER_REMOVE_PREMIUM}:{user_id}",
                style="danger",
                icon_custom_emoji_id=BE.PREMIUM
            )
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                text="Give Premium",
                callback_data=f"{Callback.USER_GIVE_PREMIUM}:{user_id}",
                style="success",
                icon_custom_emoji_id=BE.PREMIUM
            )
        ])

    if banned:
        keyboard.append([
            InlineKeyboardButton(
                text="Unban",
                callback_data=f"{Callback.USER_UNBAN}:{user_id}",
                style="success",
                icon_custom_emoji_id=BE.REFRESH_EMOJI
            )
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                text="Ban",
                callback_data=f"{Callback.USER_BAN}:{user_id}",
                style="danger",
            )
        ])

    if admin:
        keyboard.append([
            InlineKeyboardButton(
                text="Remove Admin",
                callback_data=f"{Callback.USER_REMOVE_ADMIN}:{user_id}",
                style="danger",
                icon_custom_emoji_id=BE.DELETE
            )
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                text="Add Admin",
                callback_data=f"{Callback.USER_ADD_ADMIN}:{user_id}",
                style="primary",
                icon_custom_emoji_id=BE.ADMIN
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="Back",
            callback_data=Callback.USERS,
            style="primary",
            icon_custom_emoji_id=BE.BACK_EMOJI
        ),
        InlineKeyboardButton(
            text="Close",
            callback_data=Callback.CLOSE,
            style="danger",
            icon_custom_emoji_id=BE.CLOSE_EMOJI
        ),
    ])

    return InlineKeyboardMarkup(keyboard)






def back_close_buttons(back_callback):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=back_callback,
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI
            ),
            InlineKeyboardButton(
                text="Close",
                callback_data=Callback.CLOSE,
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            ),
        ],
    ])


def refresh_back_close_buttons(refresh_callback, back_callback):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="Refresh",
                callback_data=refresh_callback,
                style="success",
                icon_custom_emoji_id=BE.REFRESH_EMOJI
            ),
        ],
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=back_callback,
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI
            ),
            InlineKeyboardButton(
                text="Close",
                callback_data=Callback.CLOSE,
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            ),
        ],
    ])






def stats_buttons():
    """Statistics page buttons."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="Refresh",
                callback_data="admin_stats_refresh",
                style="success",
                icon_custom_emoji_id=BE.REFRESH_EMOJI
            ),
        ],
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=Callback.ADMIN,
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI
            ),
            InlineKeyboardButton(
                text="Close",
                callback_data=Callback.CLOSE,
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            ),
        ],
    ])






def premium_buttons():
    """Premium page buttons."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="Refresh",
                callback_data="admin_premium_refresh",
                style="success",
                icon_custom_emoji_id=BE.REFRESH_EMOJI
            ),
        ],
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=Callback.ADMIN,
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI
            ),
            InlineKeyboardButton(
                text="Close",
                callback_data=Callback.CLOSE,
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            ),
        ],
    ])






def users_buttons(page=1, total_pages=1, user_ids=None):
    rows = []
    for user_id in user_ids or []:
        rows.append([InlineKeyboardButton(f"👤 {user_id}", callback_data=f"{Callback.USER_INFO}:{user_id}", style="primary")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀", callback_data=f"users.page:{page-1}", style="primary"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="ignore", style="primary"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶", callback_data=f"users.page:{page+1}", style="primary"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("Back", callback_data=Callback.ADMIN, style="primary", icon_custom_emoji_id=BE.BACK_EMOJI), InlineKeyboardButton("Close", callback_data=Callback.CLOSE, style="danger", icon_custom_emoji_id=BE.CLOSE_EMOJI)])
    return InlineKeyboardMarkup(rows)




def users_advanced_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=Callback.USERS,
                style="primary",
                icon_custom_emoji_id=BE.BACK_EMOJI
            ),
            InlineKeyboardButton(
                text="Close",
                callback_data=Callback.CLOSE,
                style="danger",
                icon_custom_emoji_id=BE.CLOSE_EMOJI
            ),
        ],
    ])