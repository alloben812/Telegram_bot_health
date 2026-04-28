from __future__ import annotations

"""
/today handler — daily recommendation.

Flow:
1. Get latest WHOOP snapshot + recent activities from DB
2. Build AthleteContext
3. Call TrainingPlanner.generate_daily_recommendation()
4. Save DailyRecommendation + PlannedWorkout to DB
5. Format and send to user
6. Attach Сделал/Не сделал buttons
"""

import json
import logging
from datetime import date, timedelta

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot.keyboards import MAIN_MENU_KB, workout_feedback_keyboard
from database.db import (
    get_daily_recommendation,
    get_planned_workout,
    get_recent_activities,
    get_recent_snapshots,
    get_training_profile,
    save_daily_recommendation,
    save_workout_completion,
)
from training.goals import GOAL_PRESETS
from training.hr_zones import compute_hr_zones
from training.planner import AthleteContext, _DAY_NAMES_RU, _TRAINING_DAY_LABELS, planner
from training.sports import merge_activities, normalize_sport

logger = logging.getLogger(__name__)

_INTENSITY_LABELS = {
    "z1": "Зона 1 — очень лёгкая",
    "z2": "Зона 2 — аэробная",
    "z3": "Зона 3 — темповая",
    "z4": "Зона 4 — пороговая",
    "z5": "Зона 5 — максимальная",
    "easy": "Лёгкая",
    "moderate": "Умеренная",
    "hard": "Тяжёлая",
    "rest": "Отдых",
}

_SPORT_EMOJI = {
    "run": "🏃", "bike": "🚴", "swim": "🏊", "strength": "💪",
    "hiit": "🔥", "walk": "🚶", "mobility": "🧘", "recovery": "💆",
    "rest": "😴", "other": "🏋️",
}


def _build_context(snapshots: list, activities: list, profile=None) -> AthleteContext:
    ctx = AthleteContext()

    # HR zones from user profile
    if profile and profile.max_hr:
        ctx.hr_zones = compute_hr_zones(profile.max_hr)

    # User profile: goal, training days, schedule
    if profile:
        if profile.active_goal_key:
            preset = GOAL_PRESETS.get(profile.active_goal_key)
            if preset:
                ctx.goal_label = preset.label
                ctx.goal_distance_km = preset.distance_km
                ctx.goal_target_time_min = preset.target_time_minutes
        if profile.available_training_days:
            import json as _json
            try:
                raw_days = _json.loads(profile.available_training_days) if isinstance(
                    profile.available_training_days, str
                ) else profile.available_training_days
                ctx.available_training_days = [
                    _TRAINING_DAY_LABELS.get(d, d) for d in raw_days
                ]
            except (ValueError, TypeError):
                pass
        ctx.max_run_days_per_week = profile.max_run_days_per_week
        ctx.strength_days_per_week = profile.strength_days_per_week

    # Day of week (for periodization)
    ctx.day_of_week = _DAY_NAMES_RU.get(date.today().weekday())

    if snapshots:
        today_snap = snapshots[0]
        ctx.whoop_recovery_score = today_snap.whoop_recovery_score
        ctx.whoop_hrv_ms = today_snap.whoop_hrv_ms
        ctx.whoop_resting_hr = today_snap.whoop_resting_hr
        ctx.whoop_strain_today = today_snap.whoop_strain
        ctx.whoop_sleep_performance = today_snap.whoop_sleep_performance
        ctx.whoop_spo2 = today_snap.whoop_spo2
        ctx.whoop_skin_temp = today_snap.whoop_skin_temp
        ctx.whoop_respiratory_rate = today_snap.whoop_respiratory_rate
        ctx.whoop_sleep_duration_h = today_snap.whoop_sleep_duration_h

        # Garmin: use today's snapshot first, fall back to most recent available
        for snap in snapshots:
            if snap.garmin_training_readiness is not None and ctx.garmin_training_readiness is None:
                ctx.garmin_training_readiness = snap.garmin_training_readiness
            if snap.garmin_body_battery_end is not None and ctx.garmin_body_battery is None:
                ctx.garmin_body_battery = snap.garmin_body_battery_end
            if snap.garmin_steps is not None and ctx.garmin_steps_today is None:
                ctx.garmin_steps_today = snap.garmin_steps
            if snap.garmin_stress_avg is not None and ctx.garmin_stress_avg is None:
                ctx.garmin_stress_avg = snap.garmin_stress_avg
            if snap.garmin_active_calories is not None and ctx.garmin_active_calories is None:
                ctx.garmin_active_calories = snap.garmin_active_calories

    # 7-day averages and trends (use up to 7 most recent snapshots)
    recent_7 = snapshots[:7]
    if len(recent_7) >= 2:
        hrv_vals = [s.whoop_hrv_ms for s in recent_7 if s.whoop_hrv_ms]
        if hrv_vals:
            ctx.hrv_7d_avg = round(sum(hrv_vals) / len(hrv_vals), 1)
        sleep_vals = [s.whoop_sleep_performance for s in recent_7 if s.whoop_sleep_performance]
        if sleep_vals:
            ctx.sleep_7d_avg = round(sum(sleep_vals) / len(sleep_vals), 1)

        # Recovery trend: avg of last 3 days vs previous 4
        rec_vals = [s.whoop_recovery_score for s in recent_7 if s.whoop_recovery_score is not None]
        if len(rec_vals) >= 4:
            recent_avg = sum(rec_vals[:3]) / 3
            older_avg = sum(rec_vals[3:]) / len(rec_vals[3:])
            diff = recent_avg - older_avg
            if diff > 5:
                ctx.recovery_trend = "improving"
            elif diff < -5:
                ctx.recovery_trend = "declining"
            else:
                ctx.recovery_trend = "stable"

        # Strain averages
        strain_vals = [s.whoop_strain for s in recent_7 if s.whoop_strain is not None]
        if strain_vals:
            ctx.strain_7d_avg = round(sum(strain_vals) / len(strain_vals), 1)
            ctx.weekly_strain_total = round(sum(strain_vals), 1)

        # Sleep debt: sum of (actual - 8h) over 7 days
        sleep_durations = [s.whoop_sleep_duration_h for s in recent_7 if s.whoop_sleep_duration_h is not None]
        if sleep_durations:
            debt = sum(d - 8.0 for d in sleep_durations)
            ctx.sleep_debt_h = round(debt, 1)

    if activities:
        # Deduplicate Garmin+WHOOP activities for the same workout
        activities = merge_activities(activities)

        today_str = date.today().isoformat()
        ctx.completed_today = list({
            normalize_sport(a.sport) for a in activities if a.activity_date == today_str
        })

        # Weekly load
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        week_acts = [a for a in activities if a.activity_date >= cutoff]
        load: dict = {}
        for a in week_acts:
            sport = normalize_sport(a.sport)
            if sport not in load:
                load[sport] = {"count": 0, "duration_min": 0, "distance_km": 0.0}
            load[sport]["count"] += 1
            if a.duration_s:
                load[sport]["duration_min"] += int(a.duration_s / 60)
            if a.distance_m:
                load[sport]["distance_km"] += round(a.distance_m / 1000, 1)
        ctx.weekly_load_by_sport = load

        lines = []
        for sport, data in load.items():
            emoji = _SPORT_EMOJI.get(sport, "🏋️")
            parts = [f"{emoji} {sport}: {data['count']} тр."]
            if data["duration_min"]:
                parts.append(f"{data['duration_min']} мин")
            if data["distance_km"]:
                parts.append(f"{data['distance_km']:.1f} км")
            lines.append("- " + "  ".join(parts))
        ctx.weekly_load_detail = lines

        ctx.recent_activities_db = [
            {
                "sport": normalize_sport(a.sport),
                "date": a.activity_date,
                "duration_min": int(a.duration_s / 60) if a.duration_s else None,
                "distance_km": round(a.distance_m / 1000, 1) if a.distance_m else None,
                "avg_hr": a.avg_hr,
                "whoop_strain": getattr(a, "whoop_strain", None),
            }
            for a in activities[:10]
        ]

    return ctx


def _format_recommendation(rec_record, workout_record) -> str:
    import json as _json

    lines = []
    lines.append(f"*Статус дня: готовность {rec_record.readiness_score}/100*")
    lines.append(f"_{rec_record.status_label}_\n")

    lines.append("*Главная рекомендация:*")
    lines.append(rec_record.main_recommendation + "\n")

    if workout_record:
        emoji = _SPORT_EMOJI.get(workout_record.sport, "🏋️")
        dur = f" · {workout_record.duration_minutes} мин" if workout_record.duration_minutes else ""
        intensity = _INTENSITY_LABELS.get(workout_record.intensity or "", workout_record.intensity or "")
        lines.append(f"*Тренировка на сегодня:*")
        lines.append(f"{emoji} {workout_record.title}{dur}")
        lines.append(f"Интенсивность: {intensity}\n")

        if workout_record.blocks_json:
            blocks = _json.loads(workout_record.blocks_json)
            for b in blocks:
                hr = f" · {b['target_hr_range']} уд/мин" if b.get("target_hr_range") else ""
                note = f"\n  _{b['notes']}_" if b.get("notes") else ""
                lines.append(f"• {b['title']} — {b['duration_minutes']} мин{hr}{note}")
        lines.append("")

    if rec_record.reasoning_json:
        reasoning = _json.loads(rec_record.reasoning_json)
        lines.append("*Почему:*")
        for r in reasoning:
            lines.append(f"• {r}")
        lines.append("")

    if rec_record.avoid_json:
        avoid = _json.loads(rec_record.avoid_json)
        lines.append("*Чего избегать:*")
        for a in avoid:
            lines.append(f"• {a}")
        lines.append("")

    if rec_record.control_json:
        control = _json.loads(rec_record.control_json)
        lines.append("*Контроль:*")
        for c in control:
            lines.append(f"• {c}")

    confidence_map = {"low": "🔴 низкая", "medium": "🟡 средняя", "high": "🟢 высокая"}
    conf = confidence_map.get(rec_record.confidence or "", rec_record.confidence or "")
    lines.append(f"\n_Уверенность AI: {conf}_")

    if rec_record.data_gaps_json:
        gaps = json.loads(rec_record.data_gaps_json)
        if gaps:
            lines.append(f"_Нет данных: {', '.join(gaps)}_")

    return "\n".join(lines)


async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    today = date.today().isoformat()

    msg = await update.message.reply_text("⏳ Генерирую рекомендацию на сегодня…")

    # Check if already generated today
    existing_rec = await get_daily_recommendation(user_id, today)
    existing_workout = await get_planned_workout(user_id, today)

    if existing_rec and existing_workout:
        text = _format_recommendation(existing_rec, existing_workout)
        await msg.edit_text(text, parse_mode="Markdown")
        await update.message.reply_text(
            "Тренировка выполнена?",
            reply_markup=workout_feedback_keyboard(existing_workout.id),
        )
        return

    # Build context from DB
    snapshots = await get_recent_snapshots(user_id, days=14)
    activities = await get_recent_activities(user_id, days=28)
    profile = await get_training_profile(user_id)

    if not snapshots:
        await msg.edit_text(
            "📭 Нет данных для рекомендации.\n\n"
            "Сначала сделай синхронизацию через *🔄 Синхронизация*.",
            parse_mode="Markdown",
        )
        return

    ctx = _build_context(snapshots, activities, profile)

    try:
        rec = await planner.generate_daily_recommendation(ctx)
    except RuntimeError as exc:
        await msg.edit_text(str(exc))
        return
    except ValueError as exc:
        logger.error("Daily recommendation validation failed: %s", exc)
        await msg.edit_text(
            "❌ AI вернул некорректный ответ. Попробуй ещё раз через минуту."
        )
        return

    rec_record, workout_record = await save_daily_recommendation(
        user_id=user_id,
        date=today,
        rec=rec,
    )

    text = _format_recommendation(rec_record, workout_record)

    # Split if too long
    if len(text) > 3800:
        chunks = []
        current = []
        for line in text.split("\n"):
            current.append(line)
            if len("\n".join(current)) > 3800:
                chunks.append("\n".join(current[:-1]))
                current = [line]
        if current:
            chunks.append("\n".join(current))
        await msg.edit_text(chunks[0], parse_mode="Markdown")
        for chunk in chunks[1:]:
            await update.message.reply_text(chunk, parse_mode="Markdown")
    else:
        await msg.edit_text(text, parse_mode="Markdown")

    await update.message.reply_text(
        "Тренировка выполнена?",
        reply_markup=workout_feedback_keyboard(workout_record.id),
    )


async def workout_feedback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    status = parts[1]   # done | skipped
    workout_id = int(parts[2])
    user_id = update.effective_user.id

    await save_workout_completion(
        planned_workout_id=workout_id,
        user_id=user_id,
        completion_status=status,
    )

    label = "✅ Отлично, записал!" if status == "done" else "📝 Понял, записал."
    await query.edit_message_text(label)


def get_today_handlers():
    return [
        CommandHandler("today", today_handler),
        MessageHandler(filters.Regex(r"^📅 Сегодня$"), today_handler),
        CallbackQueryHandler(workout_feedback_handler, pattern=r"^workout:(done|skipped):\d+$"),
    ]
