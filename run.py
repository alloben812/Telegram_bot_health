"""
Combined entrypoint: Telegram polling bot + FastAPI web server.

Usage:
    python run.py

Both run in the same asyncio event loop using uvicorn.Server as a
coroutine alongside PTB Application.
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


async def main():
    from telegram import Update
    from bot.main import build_application
    from web.app import app as fastapi_app

    # Build the bot (post_init will handle DB init + scheduler registration)
    bot_app = build_application()

    # Start uvicorn as an async server
    uv_config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=config.WEB_PORT,
        log_level="info",
    )
    server = uvicorn.Server(uv_config)

    # Explicitly init DB before bot starts (post_init may not fire
    # when we manage the event loop ourselves)
    from database.db import init_db
    await init_db()

    # Initialize bot (but don't call run_polling — we manage the loop)
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Telegram polling started for user_id=%d", config.ADMIN_TELEGRAM_ID)
    logger.info("Web server starting on port %d", config.WEB_PORT)

    try:
        # Run uvicorn (blocks until shutdown signal)
        await server.serve()
    finally:
        # Graceful shutdown
        logger.info("Shutting down…")
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
