from telegram.ext import CommandHandler, CallbackQueryHandler
from logger import get_logger
logger = get_logger(__name__)

try:
    from .sh import handle_sh_command
except ImportError:
    handle_sh_command = None

try:
    from .msh import handle_msh_command, export_cards as msh_export_cards, stop_mass_session as msh_stop_mass_session
except ImportError:
    handle_msh_command = msh_export_cards = msh_stop_mass_session = None

try:
    from .gen import handle_gen_command
except ImportError:
    handle_gen_command = None

try:
    from .stripe_charge import handle_st_command, handle_mst_command
except ImportError:
    handle_st_command = handle_mst_command = None

try:
    from .stripe_auth2 import handle_auth_command, handle_mauth_command
except ImportError:
    handle_auth_command = handle_mauth_command = None


def register_gates(app):
    if handle_sh_command:     app.add_handler(CommandHandler("sh",    handle_sh_command))
    if handle_msh_command:    app.add_handler(CommandHandler("msh",   handle_msh_command))
    if handle_gen_command:    app.add_handler(CommandHandler("gen",   handle_gen_command))
    if handle_st_command:     app.add_handler(CommandHandler("st",    handle_st_command))
    if handle_mst_command:    app.add_handler(CommandHandler("mst",   handle_mst_command))
    if handle_auth_command:   app.add_handler(CommandHandler("auth",  handle_auth_command))
    if handle_mauth_command:  app.add_handler(CommandHandler("mauth", handle_mauth_command))
    if msh_export_cards:      app.add_handler(CallbackQueryHandler(msh_export_cards, pattern=r"^msh_export_(charged|approved|declined|error|all)_"))
    if msh_stop_mass_session: app.add_handler(CallbackQueryHandler(msh_stop_mass_session, pattern=r"^msh_stop_"))
    logger.info("Gates registered: sh, msh, gen, st, mst, auth, mauth")

__all__ = ["register_gates"]
