"""
Training plan handlers for running, cycling, swimming, and strength.
"""

import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from bot.keyboards import MAIN_MENU_KB, back_keyboard, plan_type_keyboard
from database.db import get_latest_plan, get_recent_snapshots, save_training_plan

logger = logging.getLogger(__name__)

SPORT_MAP = {
    "🏃 Бег": "running",
    "🚴 Велосипед": "cycling",
    "🏊 Плавание": "swimming",
    "💪 Силовые": "strength",
}

SPORT_EMOJI = {
    "running": "🏃",
    "cycling": "🚴",
    "swimming": "🏊",
    "strength": "💪",
}


async def sport_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show plan type selection for the chosen sport."""
    text = update.message.text
    sport = SPORT_MAP.get(text)
    if not sport:
        return

    emoji = SPORT_EMOJI[sport]
    sport_names = {
        "running": "Бег",
        "cycling": "Велосипед",
        "swimming": "Плавание",
        "strength": "Силовые тренировки",
    }
    await update.message.reply_text(
        f"{emoji} *{sport_names[sport]}*\n\nВыбери тип плана:",
        parse_mode="Markdown",
        reply_markup=plan_type_keyboard(sport),
    )


async def plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plan generation callbacks: weekly | session | last."""
    query = update.callback_query
    await query.answer()

    _, plan_type, sport = query.data.split(":")
    user_id = update.effective_user.id

    # Show last saved plan
    if plan_type == "last":
        plan = await get_latest_plan(user_id, sport)
        if plan:
            await query.edit_message_text(
                f"📋 *Последний план ({sport})*\n\n{plan.plan_text}",
                parse_mode="Markdown",
                reply_markup=back_keyboard(f"back:sport:{sport}"),
            )
        else:
            await query.edit_message_text(
                "📋 Планов ещё нет. Сгенерируй новый!",
                reply_markup=plan_type_keyboard(sport),
            )
        return

    # Gather context from DB snapshots
    snapshots = await get_recent_snapshots(user_id, days=7)
    latest = snapshots[0] if snapshots else None

    from training.planner import AthleteContext, planner

    ctx = AthleteContext(
        whoop_recovery_score=latest.whoop_recovery_score if latest else None,
        whoop_hrv_ms=latest.whoop_hrv_ms if latest else None,
        whoop_resting_hr=latest.whoop_resting_hr if latest else None,
        whoop_strain_today=latest.whoop_strain if latest else None,
        whoop_sleep_performance=latest.whoop_sleep_performance if latest else None,
        garmin_training_readiness=latest.garmin_training_readiness if latest else None,
        garmin_steps_today=latest.garmin_steps if latest else None,
    )

    # Enrich with Garmin activity history if available
    if latest and latest.raw_garmin:
        weekly = latest.raw_garmin.get("_weekly", {})
        ctx.recent_activities = weekly.get("activities", [])
        ctx.weekly_distance_km = weekly.get("total_distance_km")
        ctx.weekly_duration_h = weekly.get("total_duration_h")
        ctx.weekly_sport_breakdown = weekly.get("sport_breakdown")

    await query.edit_message_text("🤖 Генерирую план… Это займёт несколько секунд.")

    try:
        if plan_type == "weekly":
            plan_text = await planner.generate_weekly_plan(sport, ctx)
        else:  # session
            plan_text = await planner.generate_single_session(sport, ctx)

        # Save to DB
        await save_training_plan(
            user_id=user_id,
            sport=sport,
            plan_type=plan_type,
            plan_text=plan_text,
            context_snapshot={
                "whoop_recovery": ctx.whoop_recovery_score,
                "whoop_hrv": ctx.whoop_hrv_ms,
                "garmin_readiness": ctx.garmin_training_readiness,
            },
        )

        # Telegram message limit is 4096 chars; split if needed
        if len(plan_text) > 3800:
            await query.edit_message_text(
                f"{'📅 Недельный план' if plan_type == 'weekly' else '🎯 Тренировка'} "
                f"— {SPORT_EMOJI.get(sport, '')} {sport}",
                reply_markup=back_keyboard(f"back:sport:{sport}"),
            )
            # Send full plan as follow-up messages
            for chunk in _split_text(plan_text, 4000):
                await query.message.reply_text(chunk, parse_mode="Markdown")
        else:
            label = "📅 Недельный план" if plan_type == "weekly" else "🎯 Тренировка"
            await query.edit_message_text(
                f"{label}\n\n{plan_text}",
                parse_mode="Markdown",
                reply_markup=back_keyboard(f"back:sport:{sport}"),
            )

    except Exception as exc:
        logger.error("Plan generation failed: %s", exc)
        await query.edit_message_text(
            f"❌ Ошибка генерации плана: {exc}\n\n"
            "Убедись, что в .env настроен ANTHROPIC_API_KEY.",
            reply_markup=plan_type_keyboard(sport),
        )


async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")

    if len(parts) == 3 and parts[1] == "sport":
        sport = parts[2]
        sport_names = {
            "running": "Бег",
            "cycling": "Велосипед",
            "swimming": "Плавание",
            "strength": "Силовые тренировки",
        }
        await query.edit_message_text(
            f"{SPORT_EMOJI.get(sport, '')} *{sport_names.get(sport, sport)}*\n\nВыбери тип плана:",
            parse_mode="Markdown",
            reply_markup=plan_type_keyboard(sport),
        )
    else:
        await query.edit_message_text(
            "Используй меню ниже:", reply_markup=MAIN_MENU_KB
        )


async def ask_ai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-form Q&A: any message that doesn't match a command."""
    user_id = update.effective_user.id
    question = update.message.text

    snapshots = await get_recent_snapshots(user_id, days=1)
    latest = snapshots[0] if snapshots else None

    from training.planner import AthleteContext, planner

    ctx = AthleteContext(
        whoop_recovery_score=latest.whoop_recovery_score if latest else None,
        whoop_hrv_ms=latest.whoop_hrv_ms if latest else None,
        garmin_training_readiness=latest.garmin_training_readiness if latest else None,
    )

    msg = await update.message.reply_text("🤖 Думаю…")
    try:
        answer = await planner.answer_question(question, ctx)
        await msg.edit_text(answer, parse_mode="Markdown")
    except Exception as exc:
        logger.error("AI Q&A failed: %s", exc)
        await msg.edit_text(f"❌ Ошибка: {exc}")


def _split_text(text: str, chunk_size: int) -> list[str]:
    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, chunk_size)
        if split_at == -1:
            split_at = chunk_size
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def get_plan_handlers() -> list:
    return [
        MessageHandler(
            filters.Regex(r"^(🏃 Бег|🚴 Велосипед|🏊 Плавание|💪 Силовые)$"),
            sport_menu,
        ),
        CallbackQueryHandler(plan_callback, pattern=r"^plan:"),
        CallbackQueryHandler(back_callback, pattern=r"^back:"),
    ]
