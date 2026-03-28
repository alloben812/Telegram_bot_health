from __future__ import annotations

"""
/start command and settings handlers.
"""

import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.keyboards import MAIN_MENU_KB, SETTINGS_KB, back_keyboard
from database.db import (
    get_or_create_user,
    get_user,
    update_user_garmin_credentials,
)

logger = logging.getLogger(__name__)

# Conversation states
GARMIN_EMAIL, GARMIN_PASSWORD = range(2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я твой персональный тренер с доступом к данным Garmin и WHOOP.\n\n"
        "Я умею:\n"
        "• 📊 Показывать твои показатели активности и восстановления\n"
        "• 🏃 Строить планы по бегу, велосипеду, плаванию и силовым\n"
        "• 💤 Анализировать восстановление и давать рекомендации\n"
        "• 🤖 Отвечать на вопросы о тренировках\n\n"
        "Начни с подключения устройств через ⚙️ Настройки.",
        reply_markup=MAIN_MENU_KB,
    )


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "⚙️ *Настройки*\n\nПодключи свои устройства:",
        parse_mode="Markdown",
        reply_markup=SETTINGS_KB,
    )


async def settings_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int | None:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    if action == "garmin":
        await query.edit_message_text(
            "⌚ *Настройка Garmin Connect*\n\n"
            "Введи свой email от аккаунта Garmin Connect:",
            parse_mode="Markdown",
        )
        return GARMIN_EMAIL

    if action == "whoop":
        from integrations.whoop import WhoopClient
        client = WhoopClient(update.effective_user.id)
        auth_url = client.get_auth_url()
        await query.edit_message_text(
            "💍 *Подключение WHOOP*\n\n"
            f"Перейди по ссылке для авторизации:\n{auth_url}\n\n"
            "После авторизации отправь мне код командой `/whoop_code <КОД>`",
            parse_mode="Markdown",
        )
        return None

    if action == "status":
        user = await get_user(update.effective_user.id)
        garmin_ok = bool(user and user.garmin_email and user.garmin_password_enc)
        whoop_ok = bool(user and user.whoop_token_enc)
        text = (
            "ℹ️ *Статус подключений*\n\n"
            f"⌚ Garmin Connect: {'✅ подключён' if garmin_ok else '❌ не настроен'}\n"
            f"💍 WHOOP: {'✅ подключён' if whoop_ok else '❌ не авторизован'}"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=back_keyboard("settings:back"),
        )
        return None

    return None


async def garmin_email_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data["garmin_email"] = update.message.text.strip()
    await update.message.reply_text(
        "Теперь введи пароль от Garmin Connect\n"
        "_(сообщение будет удалено после сохранения)_",
        parse_mode="Markdown",
    )
    return GARMIN_PASSWORD


async def garmin_password_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    password = update.message.text.strip()
    email = context.user_data.get("garmin_email", "")
    user_id = update.effective_user.id

    # Delete the message with the password for security
    try:
        await update.message.delete()
    except Exception:
        pass

    await update_user_garmin_credentials(user_id, email, password)
    await update.message.reply_text(
        "✅ Данные Garmin сохранены!\n\n"
        "Используй 🔄 Синхронизацию, чтобы загрузить данные.",
        reply_markup=MAIN_MENU_KB,
    )
    context.user_data.clear()
    return ConversationHandler.END


async def garmin_setup_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text("Настройка отменена.", reply_markup=MAIN_MENU_KB)
    return ConversationHandler.END


async def whoop_code_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /whoop_code <code> after OAuth redirect."""
    if not context.args:
        await update.message.reply_text(
            "Использование: `/whoop_code КОД`", parse_mode="Markdown"
        )
        return

    code = context.args[0]
    user_id = update.effective_user.id

    from integrations.whoop import WhoopClient
    from database.db import update_user_whoop_token

    client = WhoopClient(user_id)
    try:
        token = await client.exchange_code(code)
        await update_user_whoop_token(user_id, token)
        await update.message.reply_text(
            "✅ WHOOP успешно подключён!\n\n"
            "Используй 🔄 Синхронизацию, чтобы загрузить данные."
        )
    except Exception as exc:
        logger.error("WHOOP code exchange failed: %s", exc)
        await update.message.reply_text(
            f"❌ Ошибка авторизации WHOOP: {exc}\n\nПопробуй снова через ⚙️ Настройки."
        )


# ------------------------------------------------------------------ #
# Handler registration helpers
# ------------------------------------------------------------------ #

def get_garmin_conv_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(settings_callback, pattern=r"^settings:")
        ],
        states={
            GARMIN_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, garmin_email_received)
            ],
            GARMIN_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, garmin_password_received)
            ],
        },
        fallbacks=[CommandHandler("cancel", garmin_setup_cancel)],
        per_message=False,
    )
