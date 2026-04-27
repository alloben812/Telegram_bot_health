"""
Telegram bot entry point.

Run with:
    python -m bot.main
or:
    python bot/main.py
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import config
from database.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    await init_db()
    logger.info("Bot started. Listening for user_id=%d", config.ADMIN_TELEGRAM_ID)


async def error_handler(update: object, context) -> None:
    logger.error("Unhandled exception", exc_info=context.error)


def build_application() -> Application:
    config.validate()

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    from bot.auth import auth
    from bot.handlers.onboarding import get_onboarding_handler
    from bot.handlers.start import (
        get_garmin_conv_handler,
        settings_menu,
        whoop_code_command,
    )
    from bot.handlers.sync import get_sync_handlers, sync_menu
    from bot.handlers.stats import recovery_handler, stats_handler
    from bot.handlers.plans import ask_ai_handler, get_plan_handlers
    from bot.handlers.today import get_today_handlers
    from bot.handlers.history import get_history_handlers
    from bot.handlers.profile import get_profile_handlers

    # /start + onboarding conversation (handles both new and returning users)
    app.add_handler(auth(get_onboarding_handler()))

    # /whoop_code
    app.add_handler(auth(CommandHandler("whoop_code", whoop_code_command)))

    # Garmin credential setup conversation
    app.add_handler(auth(get_garmin_conv_handler()))

    # MVP core flows
    for handler in get_today_handlers():
        app.add_handler(auth(handler))

    for handler in get_history_handlers():
        app.add_handler(auth(handler))

    for handler in get_profile_handlers():
        app.add_handler(auth(handler))

    # Sync
    for handler in get_sync_handlers():
        app.add_handler(auth(handler))

    # Legacy plan handlers
    for handler in get_plan_handlers():
        app.add_handler(auth(handler))

    # Menu buttons
    app.add_handler(auth(MessageHandler(filters.Regex(r"^📊 Статистика$"), stats_handler)))
    app.add_handler(auth(MessageHandler(filters.Regex(r"^💤 Восстановление$"), recovery_handler)))
    app.add_handler(auth(MessageHandler(filters.Regex(r"^🔄 Синхронизация$"), sync_menu)))
    app.add_handler(auth(MessageHandler(filters.Regex(r"^⚙️ Настройки$"), settings_menu)))

    # Free-form Q&A catch-all — must be last
    _MENU_PATTERN = (
        r"^(📅 Сегодня|🎯 Цель|👤 Профиль|🔗 Подключить|📆 История"
        r"|📊 Статистика|💤 Восстановление|🏃 Бег|🚴 Велосипед"
        r"|🏊 Плавание|💪 Силовые|🔄 Синхронизация|⚙️ Настройки)$"
    )
    app.add_handler(
        auth(MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.Regex(_MENU_PATTERN),
            ask_ai_handler,
        ))
    )

    app.add_error_handler(error_handler)

    return app


def main() -> None:
    app = build_application()
    logger.info("Starting polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
