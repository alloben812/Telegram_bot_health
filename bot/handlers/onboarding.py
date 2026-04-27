from __future__ import annotations

"""
Onboarding conversation handler.

Collects: max HR (pre-filled from device if available), goal preset,
available training days, strength days/week.

Saves to DB at each step — does not rely on user_data surviving
across callback/message handler boundaries.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.keyboards import GOAL_KB, MAIN_MENU_KB
from database.db import (
    get_or_create_user,
    get_recent_snapshots,
    get_training_profile,
    upsert_training_profile,
)
from training.goals import GOAL_PRESETS

logger = logging.getLogger(__name__)

# Conversation states
OB_MAX_HR, OB_GOAL, OB_DAYS, OB_STRENGTH_DAYS = range(4)

_DAYS_KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Пн", callback_data="ob_day:mon"),
            InlineKeyboardButton("Вт", callback_data="ob_day:tue"),
            InlineKeyboardButton("Ср", callback_data="ob_day:wed"),
            InlineKeyboardButton("Чт", callback_data="ob_day:thu"),
        ],
        [
            InlineKeyboardButton("Пт", callback_data="ob_day:fri"),
            InlineKeyboardButton("Сб", callback_data="ob_day:sat"),
            InlineKeyboardButton("Вс", callback_data="ob_day:sun"),
        ],
        [InlineKeyboardButton("✅ Готово", callback_data="ob_day:done")],
    ]
)

_DAY_LABELS = {
    "mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
    "fri": "Пт", "sat": "Сб", "sun": "Вс",
}


async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    await get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    profile = await get_training_profile(user.id)
    if profile and profile.onboarding_done:
        await update.message.reply_text(
            f"Привет, {user.first_name}! 👋\n\n"
            "Нажми *📅 Сегодня* чтобы получить рекомендацию.",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU_KB,
        )
        return ConversationHandler.END

    # Pull absolute max HR across all recent snapshots (WHOOP + Garmin).
    # whoop_max_hr is the daily max HR recorded during workouts/cycles.
    # We take the highest value seen across all days as the best proxy for true max HR.
    suggested_hr = None
    hr_source = "whoop"
    snapshots = await get_recent_snapshots(user.id, days=90)
    for snap in snapshots:
        candidates = []
        if snap.whoop_max_hr and snap.whoop_max_hr > 150:
            candidates.append(("whoop", snap.whoop_max_hr))
        # Garmin max HR can be added here when available in model
        if candidates:
            best = max(candidates, key=lambda x: x[1])
            if suggested_hr is None or best[1] > suggested_hr:
                suggested_hr = best[1]
                hr_source = best[0]

    context.user_data["ob_suggested_hr"] = suggested_hr
    context.user_data["ob_hr_source"] = hr_source

    if suggested_hr:
        source_label = "WHOOP" if hr_source == "whoop" else "Garmin"
        hint = (
            f"Из данных {source_label} максимальный зафиксированный пульс: *{suggested_hr} уд/мин*.\n"
            "Отправь это число чтобы подтвердить, или введи другое."
        )
    else:
        hint = "Введи своё число (например 185). Его можно уточнить позже."

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}! Давай настроим профиль.\n\n"
        f"*Шаг 1/4 — Максимальный пульс*\n\n{hint}",
        parse_mode="Markdown",
    )
    return OB_MAX_HR


async def ob_max_hr_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        max_hr = int(text)
        if not (100 <= max_hr <= 230):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введи число от 100 до 230, например: 185")
        return OB_MAX_HR

    # Use device source if user confirmed the suggested value
    suggested = context.user_data.get("ob_suggested_hr")
    hr_source = context.user_data.get("ob_hr_source", "manual")
    source = hr_source if (suggested and max_hr == suggested) else "manual"

    await upsert_training_profile(
        user_id=update.effective_user.id,
        max_hr=max_hr,
        max_hr_source=source,
    )

    await update.message.reply_text(
        f"✅ Максимальный пульс: *{max_hr} уд/мин*\n\n"
        "*Шаг 2/4 — Беговая цель*\n\nВыбери цель:",
        parse_mode="Markdown",
        reply_markup=GOAL_KB,
    )
    return OB_GOAL


async def ob_goal_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    goal_key = query.data.split(":", 1)[1]

    if goal_key not in GOAL_PRESETS:
        await query.answer("Неизвестная цель", show_alert=True)
        return OB_GOAL

    # Save immediately to DB
    await upsert_training_profile(
        user_id=update.effective_user.id,
        active_goal_key=goal_key,
    )

    preset = GOAL_PRESETS[goal_key]
    await query.edit_message_text(
        f"✅ Цель: *{preset.label}*\n\n"
        "*Шаг 3/4 — Доступные дни для тренировок*\n\n"
        "Выбери дни, затем нажми ✅ Готово:",
        parse_mode="Markdown",
        reply_markup=_DAYS_KB,
    )
    return OB_DAYS


async def ob_day_toggled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]

    selected: list = context.user_data.setdefault("ob_selected_days", [])

    if action == "done":
        if not selected:
            await query.answer("Выбери хотя бы один день!", show_alert=True)
            return OB_DAYS

        # Save days to DB immediately
        await upsert_training_profile(
            user_id=update.effective_user.id,
            available_training_days=list(selected),
            max_run_days_per_week=len(selected),
        )

        days_str = ", ".join(_DAY_LABELS[d] for d in selected if d in _DAY_LABELS)
        await query.edit_message_text(
            f"✅ Дни: *{days_str}*\n\n"
            "*Шаг 4/4 — Силовые тренировки*\n\n"
            "Сколько силовых тренировок в неделю? (0–7)",
            parse_mode="Markdown",
        )
        return OB_STRENGTH_DAYS

    if action in selected:
        selected.remove(action)
    else:
        selected.append(action)

    rows = [
        [
            InlineKeyboardButton(
                f"{'✓ ' if d in selected else ''}{_DAY_LABELS[d]}",
                callback_data=f"ob_day:{d}",
            )
            for d in ["mon", "tue", "wed", "thu"]
        ],
        [
            InlineKeyboardButton(
                f"{'✓ ' if d in selected else ''}{_DAY_LABELS[d]}",
                callback_data=f"ob_day:{d}",
            )
            for d in ["fri", "sat", "sun"]
        ],
        [InlineKeyboardButton("✅ Готово", callback_data="ob_day:done")],
    ]
    await query.edit_message_reply_markup(InlineKeyboardMarkup(rows))
    return OB_DAYS


async def ob_strength_days_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text.strip()
    try:
        strength_days = int(text)
        if not (0 <= strength_days <= 7):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введи число от 0 до 7.")
        return OB_STRENGTH_DAYS

    user_id = update.effective_user.id

    # Save final field + mark onboarding done
    await upsert_training_profile(
        user_id=user_id,
        strength_days_per_week=strength_days,
        onboarding_done=True,
    )

    # Read back profile to show summary
    from database.db import get_training_profile as _get
    profile = await _get(user_id)
    goal = GOAL_PRESETS.get(profile.active_goal_key or "", None)
    goal_label = goal.label if goal else "не выбрана"

    import json as _json
    days_raw = _json.loads(profile.available_training_days or "[]")
    days_str = ", ".join(_DAY_LABELS.get(d, d) for d in days_raw) or "—"

    context.user_data.pop("ob_selected_days", None)

    await update.message.reply_text(
        "🎉 *Профиль настроен!*\n\n"
        f"• Макс. пульс: *{profile.max_hr or '—'} уд/мин*\n"
        f"• Цель: *{goal_label}*\n"
        f"• Дни тренировок: *{days_str}*\n"
        f"• Силовых дней/нед: *{strength_days}*\n\n"
        "Теперь нажми *📅 Сегодня* чтобы получить рекомендацию.\n"
        "_Не забудь синхронизировать устройства через 🔄 Синхронизация_",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU_KB,
    )
    return ConversationHandler.END


async def ob_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("ob_selected_days", None)
    await update.message.reply_text(
        "Настройка отменена. Запусти /start чтобы начать заново.",
        reply_markup=MAIN_MENU_KB,
    )
    return ConversationHandler.END


def get_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start_onboarding)],
        states={
            OB_MAX_HR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_max_hr_received)],
            OB_GOAL: [CallbackQueryHandler(ob_goal_received, pattern=r"^ob_goal:")],
            OB_DAYS: [CallbackQueryHandler(ob_day_toggled, pattern=r"^ob_day:")],
            OB_STRENGTH_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_strength_days_received)],
        },
        fallbacks=[CommandHandler("cancel", ob_cancel)],
        per_message=False,
    )
