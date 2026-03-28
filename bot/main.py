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


def build_application() -> Application:
    # Fail immediately if any required env var is missing
    config.validate()

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    from bot.auth import auth
    from bot.handlers.start import (
        get_garmin_conv_handler,
        settings_menu,
        start,
        whoop_code_command,
    )
    from bot.handlers.sync import get_sync_handlers, sync_menu
    from bot.handlers.stats import recovery_handler, stats_handler
    from bot.handlers.plans import ask_ai_handler, get_plan_handlers

    # All handlers are wrapped with auth() — only ADMIN_TELEGRAM_ID can use the bot
    app.add_handler(auth(CommandHandler("start", start)))
    app.add_handler(auth(CommandHandler("whoop_code", whoop_code_command)))

    # Garmin setup conversation (ConversationHandler wraps multiple handlers internally)
    # We wrap the ConversationHandler itself
    app.add_handler(auth(get_garmin_conv_handler()))

    for handler in get_sync_handlers():
        app.add_handler(auth(handler))

    for handler in get_plan_handlers():
        app.add_handler(auth(handler))

    app.add_handler(auth(MessageHandler(filters.Regex(r"^📊 Статистика$"), stats_handler)))
    app.add_handler(auth(MessageHandler(filters.Regex(r"^💤 Восстановление$"), recovery_handler)))
    app.add_handler(auth(MessageHandler(filters.Regex(r"^🔄 Синхронизация$"), sync_menu)))
    app.add_handler(auth(MessageHandler(filters.Regex(r"^⚙️ Настройки$"), settings_menu)))

    # Free-form Q&A catch-all — must be last
    app.add_handler(
        auth(MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.Regex(
                r"^(📊 Статистика|💤 Восстановление|🏃 Бег|🚴 Велосипед"
                r"|🏊 Плавание|💪 Силовые|🔄 Синхронизация|⚙️ Настройки)$"
            ),
            ask_ai_handler,
        ))
    )

    return app


def main() -> None:
    app = build_application()
    logger.info("Starting polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
