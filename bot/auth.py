"""
Authorization middleware.

The bot is strictly personal — it only responds to the Telegram user ID
listed in ADMIN_TELEGRAM_ID. All other users receive a one-line rejection.

This is enforced at the Application level via a custom BaseHandler wrapper,
so no handler code needs to repeat the check.
"""

import logging
from typing import Any

from telegram import Update
from telegram.ext import BaseHandler, ContextTypes

from config import config

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHandler):
    """Wraps another handler and gates access by Telegram user ID."""

    def __init__(self, inner: BaseHandler) -> None:
        # Use the inner handler's callback for the superclass; we override check/handle.
        super().__init__(inner.callback)
        self._inner = inner

    def check_update(self, update: object) -> Any:
        return self._inner.check_update(update)

    async def handle_update(
        self,
        update: Update,
        application: Any,
        check_result: Any,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        user = update.effective_user
        if user is None or user.id != config.ADMIN_TELEGRAM_ID:
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ Этот бот приватный и не доступен публично."
                )
            logger.warning(
                "Blocked unauthorized access from user_id=%s username=%s",
                user.id if user else "unknown",
                user.username if user else "unknown",
            )
            return

        await self._inner.handle_update(update, application, check_result, context)


def auth(handler: BaseHandler) -> AuthMiddleware:
    """Convenience wrapper: auth(CommandHandler(...))"""
    return AuthMiddleware(handler)
