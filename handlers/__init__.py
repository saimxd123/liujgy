

from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from logger import get_logger





logger = get_logger(__name__)





from handlers.start import register_start
from plans import register_plans
from handlers.profile import register_profile
from handlers.admin import register_admin, admin_page_callback









from handlers.stats import register_stats
from handlers.report import register_report





from handlers.proxy import register_proxy
from handlers.sites import register_sites





from handlers.admin_commands import register_admin_commands
from handlers.genkey import register_genkey
from handlers.redeem import register_redeem





from handlers.lock import register_lock_commands
from handlers.owner_panel import register_owner_panel





from handlers.speed import register_speed





from handlers.admin import session_command, vps_command





from handlers.fb import register_fb





from handlers.txt import register_txt





try:
    from bin import register_bin
    BIN_AVAILABLE = True
    logger.info("✅ /bin command imported successfully")
except ImportError as e:
    register_bin = None
    BIN_AVAILABLE = False
    logger.warning(f"❌ /bin import failed: {e}")





try:
    from handlers.scr import handle_scr_command
    logger.info("✅ /scr command imported successfully")
except ImportError as e:
    logger.warning(f"❌ /scr import failed: {e}")
    handle_scr_command = None





try:
    from gates.gen import handle_gen_command
    logger.info("✅ /gen command imported successfully")
except ImportError as e:
    logger.warning(f"❌ /gen import failed: {e}")
    handle_gen_command = None





try:
    from hitter import register_hit
    logger.info("✅ /hit command imported successfully")
except ImportError as e:
    logger.warning(f"❌ /hit import failed: {e}")
    register_hit = None





try:
    from jio import handle_jhit_command, jauth_command, junauth_command, jiolist_command
    JHIT_AVAILABLE = True
    logger.info("✅ /jhit, /jauth, /junauth, /jiolist imported successfully")
except ImportError as e:
    handle_jhit_command = None
    jauth_command = None
    junauth_command = None
    jiolist_command = None
    JHIT_AVAILABLE = False
    logger.warning(f"❌ Jio commands import failed: {e}")





from forcejoin import check_joined_callback





try:
    from handlers.fake import register_fake
    logger.info("✅ /fake and /fakehelp commands imported successfully")
except ImportError as e:
    logger.warning(f"❌ /fake import failed: {e}")
    register_fake = None





try:
    from handlers.broad import register_broad
    logger.info("✅ /broad, /stopbroad, /broadstatus commands imported successfully")
except ImportError as e:
    logger.warning(f"❌ /broad import failed: {e}")
    register_broad = None





try:
    from handlers.dorks import register_dorks
    logger.info("✅ /dorks imported successfully")
except ImportError as e:
    register_dorks = None
    logger.warning(f"❌ /dorks import failed: {e}")





try:
    from handlers.buy import register_buy
    logger.info("✅ /buy command imported successfully")
except ImportError as e:
    logger.warning(f"❌ /buy import failed: {e}")
    register_buy = None
    



try:   
    from gates.gate import handle_gate_command
    logger.info("✅ /gate command imported successfully")
except ImportError as e:
    logger.warning(f"❌ /gate import failed: {e}")  






def register_handlers(app: Application):
    """Register all bot handlers."""





    register_start(app)
    register_plans(app)
    register_profile(app)
    register_admin(app)





    register_stats(app)
    register_report(app)








    register_proxy(app)
    register_sites(app)





    register_admin_commands(app)
    register_genkey(app)
    register_redeem(app)





    register_lock_commands(app)
    register_owner_panel(app)





    register_speed(app)





    register_fb(app)





    register_txt(app)





    app.add_handler(
        CommandHandler("session", session_command)
    )

    app.add_handler(
        CommandHandler("vps", vps_command)
    )
    
    app.add_handler(CommandHandler("gate", handle_gate_command))





    app.add_handler(
        CallbackQueryHandler(
            admin_page_callback,
            pattern=r"^admin_page:"
        )
    )





    if BIN_AVAILABLE and register_bin:
        register_bin(app)
        logger.info("✅ /bin command registered")
    else:
        logger.warning(
            "❌ /bin command NOT registered (import failed)"
        )





    if handle_scr_command:
        app.add_handler(
            CommandHandler("scr", handle_scr_command)
        )
        logger.info("✅ /scr command registered")
    else:
        logger.warning(
            "❌ /scr command NOT registered (import failed)"
        )





    if handle_gen_command:
        app.add_handler(
            CommandHandler("gen", handle_gen_command)
        )
        logger.info("✅ /gen command registered")
    else:
        logger.warning(
            "❌ /gen command NOT registered (import failed)"
        )





    if register_hit:
        register_hit(app)
        logger.info("✅ /hit command registered")
    else:
        logger.warning(
            "❌ /hit command NOT registered (import failed)"
        )





    if JHIT_AVAILABLE:
        if handle_jhit_command:
            app.add_handler(
                CommandHandler("jhit", handle_jhit_command)
            )
            logger.info("✅ /jhit command registered")
        if jauth_command:
            app.add_handler(
                CommandHandler("jauth", jauth_command)
            )
            logger.info("✅ /jauth command registered")
        if junauth_command:
            app.add_handler(
                CommandHandler("junauth", junauth_command)
            )
            logger.info("✅ /junauth command registered")
        if jiolist_command:
            app.add_handler(
                CommandHandler("jiolist", jiolist_command)
            )
            logger.info("✅ /jiolist command registered")
    else:
        logger.warning(
            "❌ Jio commands NOT registered (import failed)"
        )





    app.add_handler(
        CallbackQueryHandler(
            check_joined_callback,
            pattern=r"^check_joined$"
        )
    )





    if register_fake:
        register_fake(app)
        logger.info(
            "✅ /fake and /fakehelp commands registered"
        )
    else:
        logger.warning(
            "❌ /fake commands NOT registered (import failed)"
        )





    if register_broad:
        register_broad(app)
        logger.info(
            "✅ /broad, /stopbroad, /broadstatus commands registered"
        )
    else:
        logger.warning(
            "❌ /broad commands NOT registered (import failed)"
        )





    if register_dorks:
        register_dorks(app)
        logger.info("✅ /dorks command registered")
    else:
        logger.warning(
            "❌ /dorks command NOT registered (import failed)"
        )





    if register_buy:
        register_buy(app)
        logger.info("✅ /buy command registered")
    else:
        logger.warning(
            "❌ /buy command NOT registered (import failed)"
        )









    from handlers.callback_router import register_callback

    register_callback(app)

    logger.info(
        "✅ Generic callback router registered LAST"
    )

    logger.info(
        "✅ All handlers registered successfully."
    )