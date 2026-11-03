

from handlers.callback.users import users_page
from handlers.callback.stats import statistics_page
from handlers.callback.premium import premium_page
from core.callbacks import Callback


async def open_users(query):
    await users_page(query)


async def open_premium(query):
    await premium_page(query)


async def open_statistics(query):
    await statistics_page(query)


ADMIN_CALLBACKS = {
    Callback.USERS: open_users,
    Callback.STATS: open_statistics,
    Callback.PREMIUM: open_premium,
}