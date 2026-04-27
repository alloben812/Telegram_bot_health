from __future__ import annotations

"""Profile and Goal handlers."""

import json
import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot.keyboards import PROFILE_GOAL_KB, MAIN_MENU_KB, back_keyboard
from database.db import get_training_profile, upsert_training_profile
from training.goals import GOAL_PRESETS

logger = logging.getLogger(__name__)

_DAY_LABELS = {
    "mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
    "fri": "Пт", "sat": "Сб", "sun": "Вс",
}


async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    profile = await get_training_profile(user_id)

    if not profile or not profile.onboarding_done:
        await update.message.reply_text(
            "Профиль не настроен. Запусти /start для онбординга.",
            reply_markup=MAIN_MENU_KB,
        )
        return

    goal = GOAL_PRESETS.get(profile.active_goal_key or "", None)
    goal_label = goal.label if goal else "не выбрана"

    days_raw = json.loads(profile.available_training_days or "[]")
    days_str = ", ".join(_DAY_LABELS.get(d, d) for d in days_raw) or "не указаны"

    hr_source = {"manual": "вручную", "garmin": "Garmin", "whoop": "WHOOP"}.get(
        profile.max_hr_source or "manual", profile.max_hr_source or ""
    )

    text = (
        "*👤 Профиль*\n\n"
        f"• Макс. пульс: *{profile.max_hr or '—'} уд/мин* ({hr_source})\n"
        f"• Цель: *{goal_label}*\n"
        f"• Дни тренировок: *{days_str}*\n"
        f"• Беговых дней/нед: *{profile.max_run_days_per_week or '—'}*\n"
        f"• Силовых дней/нед: *{profile.strength_days_per_week or '—'}*\n\n"
        "_Для изменения цели нажми 🎯 Цель_"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MAIN_MENU_KB)


async def goal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    profile = await get_training_profile(user_id)
    current = profile.active_goal_key if profile else None
    current_label = GOAL_PRESETS[current].label if current and current in GOAL_PRESETS else "не выбрана"

    await update.message.reply_text(
        f"*🎯 Цель*\n\nТекущая цель: *{current_label}*\n\nВыбери новую:",
        parse_mode="Markdown",
        reply_markup=PROFILE_GOAL_KB,
    )


async def goal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    goal_key = query.data.split(":", 1)[1]  # set_goal:key

    if goal_key not in GOAL_PRESETS:
        await query.edit_message_text("Неизвестная цель.")
        return

    user_id = update.effective_user.id
    await upsert_training_profile(user_id=user_id, active_goal_key=goal_key)
    preset = GOAL_PRESETS[goal_key]
    await query.edit_message_text(
        f"✅ Цель обновлена: *{preset.label}*",
        parse_mode="Markdown",
    )


async def connect_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔗 *Подключение устройств*\n\n"
        "Используй ⚙️ Настройки для подключения Garmin и WHOOP.\n\n"
        "_Web Connect UI появится в следующей фазе._",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU_KB,
    )


def get_profile_handlers():
    return [
        CommandHandler("profile", profile_handler),
        CommandHandler("goal", goal_handler),
        MessageHandler(filters.Regex(r"^👤 Профиль$"), profile_handler),
        MessageHandler(filters.Regex(r"^🎯 Цель$"), goal_handler),
        MessageHandler(filters.Regex(r"^🔗 Подключить$"), connect_handler),
        CallbackQueryHandler(goal_callback, pattern=r"^set_goal:"),
    ]
