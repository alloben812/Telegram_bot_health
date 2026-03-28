"""
Telegram bot entry point.

Run with:
    python -m bot.main
or:
    python bot/main.py
"""

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

# Make sure repo root is in sys.path when running directly
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from database.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Called after the bot starts — initialise the database."""
    await init_db()
    logger.info("Bot started. Database ready.")


def build_application() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env")

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ------------------------------------------------------------------ #
    # Import handlers
    # ------------------------------------------------------------------ #
    from bot.handlers.start import (
        get_garmin_conv_handler,
        settings_menu,
        start,
        whoop_code_command,
    )
    from bot.handlers.sync import get_sync_handlers, sync_menu
    from bot.handlers.stats import recovery_handler, stats_handler
    from bot.handlers.plans import ask_ai_handler, get_plan_handlers

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whoop_code", whoop_code_command))

    # Garmin setup conversation (must be before other handlers)
    app.add_handler(get_garmin_conv_handler())

    # Sync callbacks
    for handler in get_sync_handlers():
        app.add_handler(handler)

    # Plan callbacks
    for handler in get_plan_handlers():
        app.add_handler(handler)

    # Reply keyboard text handlers
    app.add_handler(
        MessageHandler(filters.Regex(r"^📊 Статистика$"), stats_handler)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^💤 Восстановление$"), recovery_handler)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🔄 Синхронизация$"), sync_menu)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^⚙️ Настройки$"), settings_menu)
    )

    # Free-form Q&A — catch-all (must be last)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.Regex(
                r"^(📊 Статистика|💤 Восстановление|🏃 Бег|🚴 Велосипед"
                r"|🏊 Плавание|💪 Силовые|🔄 Синхронизация|⚙️ Настройки)$"
            ),
            ask_ai_handler,
        )
    )

    return app


def main() -> None:
    app = build_application()
    logger.info("Starting polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
