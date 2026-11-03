

from core.callbacks import Callback
from ui.pages import (
    home_page,
    profile_page,
    settings_page,
    help_page,
    commands_page,
    pricing_page,
    admin_panel,
)

PAGE_CALLBACKS = {

    Callback.HOME: home_page,
    Callback.PROFILE: profile_page,
    Callback.SETTINGS: settings_page,
    Callback.HELP: help_page,
    Callback.COMMANDS: commands_page,
    Callback.PRICING: pricing_page,
    Callback.ADMIN: admin_panel,
}