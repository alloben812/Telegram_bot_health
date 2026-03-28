"""
Stats and recovery handlers.
"""

from __future__ import annotations
import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.db import get_recent_activities, get_recent_snapshots, get_user

logger = logging.getLogger(__name__)

_SPORT_EMOJI: dict[str, str] = {
    "running": "🏃",
    "cycling": "🚴",
    "swimming": "🏊",
    "strength": "💪",
    "functional_fitness": "🏋️",
    "hiit": "⚡",
    "rowing": "🚣",
    "yoga": "🧘",
    "pilates": "🧘",
    "triathlon": "🏅",
    "walking": "🚶",
    "hiking": "🥾",
    "soccer": "⚽",
    "basketball": "🏀",
    "tennis": "🎾",
    "boxing": "🥊",
    "mma": "🥋",
    "crossfit": "🏋️",
    "ski": "⛷️",
    "activity": "🏃",
}


def _recovery_emoji(score: float | None) -> str:
    if score is None:
        return "⚪"
    if score >= 67:
        return "🟢"
    if score >= 34:
        return "🟡"
    return "🔴"


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show last 7-day stats summary + 4-week workout list."""
    user_id = update.effective_user.id
    snapshots = await get_recent_snapshots(user_id, days=7)
    garmin_acts = await get_recent_activities(user_id, days=28, source="garmin")
    whoop_acts = await get_recent_activities(user_id, days=28, source="whoop")

    if not snapshots and not garmin_acts and not whoop_acts:
        await update.message.reply_text(
            "📊 Нет данных. Выполни 🔄 Синхронизацию, чтобы загрузить показатели."
        )
        return

    lines = ["📊 *Статистика за последние 7 дней*\n"]

    for s in reversed(snapshots):
        rec = s.whoop_recovery_score
        strain = s.whoop_strain
        hrv = s.whoop_hrv_ms
        rhr = s.whoop_resting_hr
        sleep_p = s.whoop_sleep_performance
        sleep_h = s.whoop_sleep_duration_h
        avg_hr = s.whoop_avg_hr
        max_hr = s.whoop_max_hr
        kj = s.whoop_kilojoule
        workouts = s.whoop_workout_count
        emoji = _recovery_emoji(rec)

        line = f"📅 *{s.snapshot_date}*\n"
        if rec is not None:
            line += f"  {emoji} Recovery: {rec:.0f}%"
            if hrv:
                line += f"  HRV: {hrv:.0f}мс"
            if rhr:
                line += f"  ЧСС п.: {rhr:.0f}"
            line += "\n"
        if strain is not None:
            line += f"  ⚡ Strain: {strain:.1f}/21"
            if avg_hr:
                line += f"  ❤️ avg: {avg_hr}"
            if max_hr:
                line += f"  max: {max_hr}"
            line += "\n"
        if kj is not None:
            kcal = round(kj / 4.184)
            line += f"  🔥 Калории: {kcal} ккал\n"
        if sleep_p is not None:
            line += f"  😴 Сон: {sleep_p:.0f}%"
            if sleep_h:
                line += f" ({sleep_h:.1f}ч)"
            line += "\n"
        if workouts:
            line += f"  🏋️ Тренировок: {workouts}\n"

        lines.append(line)

    # Garmin summary from latest snapshot
    if snapshots:
        latest = snapshots[0]
        if latest.garmin_steps or latest.garmin_active_calories:
            lines.append(
                f"\n⌚ *Garmin ({latest.snapshot_date}):*\n"
                f"  Шаги: {latest.garmin_steps or '—':,}\n"
                f"  Активные ккал: {latest.garmin_active_calories or '—'}\n"
                f"  Готовность: {latest.garmin_training_readiness or '—'}/100"
            )

    # Workout list for the past 4 weeks — both sources, equal weight
    garmin_acts = await get_recent_activities(user_id, days=28, source="garmin")
    whoop_acts = await get_recent_activities(user_id, days=28, source="whoop")

    if whoop_acts:
        lines.append(f"\n\n💍 *Тренировки WHOOP (4 нед.) — {len(whoop_acts)} шт:*\n")
        for a in whoop_acts[:25]:
            sport_e = _SPORT_EMOJI.get(a.sport, "🏃")
            dur = f"{int(a.duration_s // 60)}мин" if a.duration_s else "—"
            dist = f"{a.distance_m / 1000:.1f}км" if a.distance_m else ""
            hr = f"пульс {a.avg_hr}" if a.avg_hr else ""
            strain_str = f"strain {a.whoop_strain:.1f}" if a.whoop_strain else ""
            details = "  ".join(filter(None, [dur, dist, hr, strain_str]))
            lines.append(f"{sport_e} {a.activity_date}  {a.sport}  {details}")
        if len(whoop_acts) > 25:
            lines.append(f"_…и ещё {len(whoop_acts) - 25}_")

    if garmin_acts:
        lines.append(f"\n\n⌚ *Тренировки Garmin (4 нед.) — {len(garmin_acts)} шт:*\n")
        for a in garmin_acts[:25]:
            sport_e = _SPORT_EMOJI.get(a.sport, "🏃")
            dur = f"{int(a.duration_s // 60)}мин" if a.duration_s else "—"
            dist = f"{a.distance_m / 1000:.1f}км" if a.distance_m else ""
            pace_str = ""
            if a.avg_pace_s_per_km:
                m, s = divmod(int(a.avg_pace_s_per_km), 60)
                pace_str = f"{m}:{s:02d}/км"
            hr = f"пульс {a.avg_hr}" if a.avg_hr else ""
            elev = f"↑{a.elevation_gain_m:.0f}м" if a.elevation_gain_m else ""
            details = "  ".join(filter(None, [dur, dist, pace_str, hr, elev]))
            lines.append(f"{sport_e} {a.activity_date}  {a.sport}  {details}")
        if len(garmin_acts) > 25:
            lines.append(f"_…и ещё {len(garmin_acts) - 25}_")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


async def recovery_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show recovery analysis for today + AI recommendation."""
    user_id = update.effective_user.id
    user = await get_user(user_id)
    snapshots = await get_recent_snapshots(user_id, days=1)

    if not snapshots:
        await update.message.reply_text(
            "💤 Нет данных о восстановлении. Выполни 🔄 Синхронизацию."
        )
        return

    s = snapshots[0]
    emoji = _recovery_emoji(s.whoop_recovery_score)

    lines = [
        f"💤 *Восстановление на {s.snapshot_date}*\n",
        f"{emoji} *WHOOP Recovery:* {s.whoop_recovery_score or '—'}%",
        f"💓 *HRV:* {s.whoop_hrv_ms or '—'} мс",
        f"❤️ *ЧСС покоя:* {s.whoop_resting_hr or '—'} уд/мин",
        f"😴 *Качество сна:* {s.whoop_sleep_performance or '—'}%",
        f"⚡ *Strain:* {s.whoop_strain or '—'}/21",
    ]

    if s.garmin_training_readiness:
        lines.append(f"⌚ *Готовность (Garmin):* {s.garmin_training_readiness}/100")

    # Determine readiness level
    rec = s.whoop_recovery_score
    if rec is not None:
        if rec >= 67:
            advice = "🟢 Отличное восстановление — можно работать на высокой интенсивности."
        elif rec >= 34:
            advice = "🟡 Умеренное восстановление — рекомендуется тренировка средней интенсивности."
        else:
            advice = "🔴 Низкое восстановление — лучше активный отдых или лёгкая восстановительная работа."
        lines.append(f"\n{advice}")

    # AI analysis (if Anthropic key configured)
    if user and (s.whoop_recovery_score is not None or s.garmin_training_readiness):
        lines.append("\n⏳ _Получаю AI-анализ…_")
        msg = await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown"
        )

        try:
            from training.planner import AthleteContext, planner

            ctx = AthleteContext(
                whoop_recovery_score=s.whoop_recovery_score,
                whoop_hrv_ms=s.whoop_hrv_ms,
                whoop_resting_hr=s.whoop_resting_hr,
                whoop_strain_today=s.whoop_strain,
                whoop_sleep_performance=s.whoop_sleep_performance,
                garmin_training_readiness=s.garmin_training_readiness,
                garmin_steps_today=s.garmin_steps,
            )
            analysis = await planner.analyze_recovery(ctx)
            lines[-1] = f"\n🤖 *AI-анализ восстановления:*\n{analysis}"
            await msg.edit_text("\n".join(lines), parse_mode="Markdown")
        except Exception as exc:
            logger.warning("AI recovery analysis failed: %s", exc)
            lines[-1] = ""
            await msg.edit_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
