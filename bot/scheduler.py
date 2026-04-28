from __future__ import annotations

"""
Scheduled jobs for the Telegram bot.

Schedule (Europe/Belgrade timezone):
  07:00 — sync Garmin + WHOOP → generate + push daily recommendation
  12:00 — silent sync
  17:00 — silent sync
  21:00 — silent sync
"""

import logging
from datetime import date, time
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from config import config

logger = logging.getLogger(__name__)

BELGRADE_TZ = ZoneInfo("Europe/Belgrade")

_SILENT_SYNC_TIMES = [
    time(hour=12, minute=0),
    time(hour=17, minute=0),
    time(hour=21, minute=0),
]


# ------------------------------------------------------------------ #
# Core sync helper (no Telegram update object required)
# ------------------------------------------------------------------ #

async def _do_sync(user_id: int) -> tuple[bool, list[str]]:
    """Run Garmin + WHOOP sync for a user.

    Returns (any_data_saved, errors).
    """
    from datetime import date as _date
    from database.db import (
        get_user,
        save_garmin_activities,
        save_whoop_workouts,
        upsert_daily_snapshot,
    )
    from bot.handlers.sync import (
        _build_garmin_client,
        _build_whoop_client,
        _persist_whoop_token,
    )

    user = await get_user(user_id)
    if not user:
        return False, ["User not found in DB"]

    garmin_data = None
    whoop_data = None
    errors: list[str] = []
    today = _date.today()

    # ---- Garmin ----
    try:
        gc = await _build_garmin_client(user)
        garmin_data = await gc.get_daily_summary(today)
        garmin_data["_weekly"] = await gc.get_weekly_summary()
        today_acts = await gc.get_activities_by_date(today, today)
        garmin_data["_activities"] = today_acts
        if today_acts:
            await save_garmin_activities(user_id, today_acts)
        # Fetch training readiness and body battery (extra API calls)
        try:
            garmin_data["_training_readiness"] = await gc.get_training_readiness(today)
        except Exception:
            pass
        try:
            garmin_data["_body_battery"] = await gc.get_body_battery(today)
        except Exception:
            pass
        logger.info("Scheduled Garmin sync OK for user %d", user_id)
    except Exception as exc:
        logger.warning("Scheduled Garmin sync error for user %d: %s", user_id, exc)
        errors.append(f"Garmin: {exc}")

    # ---- WHOOP ----
    try:
        wc = await _build_whoop_client(user, user_id)
        recovery = await wc.get_latest_recovery()
        sleep = await wc.get_latest_sleep()
        cycle = await wc.get_latest_cycle()
        today_workouts = await wc.get_workout_collection(limit=10)
        await _persist_whoop_token(user_id)

        if recovery or sleep or cycle or today_workouts:
            whoop_data = {
                "recovery": recovery or {},
                "sleep": sleep or {},
                "cycle": cycle or {},
                "workouts": today_workouts,
            }
            if today_workouts:
                await save_whoop_workouts(user_id, today_workouts)
        logger.info("Scheduled WHOOP sync OK for user %d", user_id)
    except Exception as exc:
        logger.warning("Scheduled WHOOP sync error for user %d: %s", user_id, exc)
        errors.append(f"WHOOP: {exc}")

    if garmin_data or whoop_data:
        await upsert_daily_snapshot(
            user_id=user_id,
            snapshot_date=today.isoformat(),
            garmin_data=garmin_data,
            whoop_data=whoop_data,
        )
        return True, errors

    return False, errors


# ------------------------------------------------------------------ #
# Job: silent sync (12:00, 17:00, 21:00)
# ------------------------------------------------------------------ #

async def job_silent_sync(context: ContextTypes.DEFAULT_TYPE) -> None:
    from database.db import (
        get_activities_for_date,
        get_planned_workout,
        save_workout_completion,
    )
    from training.sports import normalize_sport

    user_id = config.ADMIN_TELEGRAM_ID
    today = date.today().isoformat()
    logger.info("Silent sync starting for user %d", user_id)

    # Snapshot activities before sync
    before = await get_activities_for_date(user_id, today)
    before_ids = {a.external_id for a in before}

    saved, errors = await _do_sync(user_id)
    if errors:
        logger.warning("Silent sync finished with errors: %s", errors)
    else:
        logger.info("Silent sync OK, data_saved=%s", saved)

    # Check for new activities detected after sync
    after = await get_activities_for_date(user_id, today)
    new_activities = [a for a in after if a.external_id not in before_ids]

    if new_activities:
        planned = await get_planned_workout(user_id, today)
        for act in new_activities:
            sport = normalize_sport(act.sport)
            dur_min = int(act.duration_s / 60) if act.duration_s else None
            strain_str = f" (strain {act.whoop_strain:.1f})" if act.whoop_strain else ""
            dur_str = f" {dur_min} мин" if dur_min else ""

            from training.planner import _SPORT_LABELS
            sport_label = _SPORT_LABELS.get(sport, sport)
            emoji = {"run": "🏃", "bike": "🚴", "swim": "🏊", "strength": "💪",
                     "hiit": "🔥", "walk": "🚶", "mobility": "🧘"}.get(sport, "🏋️")

            msg = f"{emoji} Обнаружена тренировка: {sport_label}{dur_str}{strain_str}"

            # Auto-complete planned workout if sport matches
            if planned and planned.status == "proposed":
                planned_sport = normalize_sport(planned.sport)
                if planned_sport == sport:
                    await save_workout_completion(
                        planned_workout_id=planned.id,
                        user_id=user_id,
                        completion_status="auto_detected",
                    )
                    msg += "\n✅ Рекомендация на сегодня выполнена!"
                    logger.info("Auto-completed planned workout %d for user %d", planned.id, user_id)

            try:
                await context.bot.send_message(chat_id=user_id, text=msg)
            except Exception as exc:
                logger.warning("Failed to send workout notification: %s", exc)


# ------------------------------------------------------------------ #
# Job: morning push (07:00) — sync → generate → send
# ------------------------------------------------------------------ #

async def job_morning_push(context: ContextTypes.DEFAULT_TYPE) -> None:
    from database.db import (
        get_daily_recommendation,
        get_recent_activities,
        get_recent_snapshots,
        get_training_profile,
        save_daily_recommendation,
    )
    from bot.handlers.today import _build_context, _format_recommendation
    from bot.keyboards import workout_feedback_keyboard
    from training.planner import planner

    user_id = config.ADMIN_TELEGRAM_ID
    today = date.today().isoformat()
    logger.info("Morning push starting for user %d date=%s", user_id, today)

    # 1. Sync first so we have fresh data
    await _do_sync(user_id)

    # 2. Skip if already sent today (e.g. bot restarted after push)
    existing = await get_daily_recommendation(user_id, today)
    if existing:
        logger.info("Morning push: recommendation already exists for %s — skipping", today)
        return

    # 3. Build athlete context
    snapshots = await get_recent_snapshots(user_id, days=14)
    if not snapshots:
        logger.warning("Morning push: no snapshots for user %d — no recommendation sent", user_id)
        return

    activities = await get_recent_activities(user_id, days=28)
    profile = await get_training_profile(user_id)
    ctx = _build_context(snapshots, activities, profile)

    # 4. Generate recommendation via AI
    try:
        rec = await planner.generate_daily_recommendation(ctx)
    except Exception as exc:
        logger.error("Morning push: AI error for user %d: %s", user_id, exc)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ Не удалось сгенерировать утреннюю рекомендацию: {exc}",
            )
        except Exception:
            pass
        return

    # 5. Persist
    rec_record, workout_record = await save_daily_recommendation(
        user_id=user_id,
        date=today,
        rec=rec,
    )

    # 6. Format and send
    body = _format_recommendation(rec_record, workout_record)
    header = "🌅 *Доброе утро! Рекомендация на сегодня:*\n\n"
    full_text = header + body

    if len(full_text) > 3800:
        chunks: list[str] = []
        current: list[str] = []
        for line in full_text.split("\n"):
            current.append(line)
            if len("\n".join(current)) > 3800:
                chunks.append("\n".join(current[:-1]))
                current = [line]
        if current:
            chunks.append("\n".join(current))
        await context.bot.send_message(
            chat_id=user_id, text=chunks[0], parse_mode="Markdown"
        )
        for chunk in chunks[1:]:
            await context.bot.send_message(
                chat_id=user_id, text=chunk, parse_mode="Markdown"
            )
    else:
        await context.bot.send_message(
            chat_id=user_id, text=full_text, parse_mode="Markdown"
        )

    if workout_record:
        await context.bot.send_message(
            chat_id=user_id,
            text="Тренировка выполнена?",
            reply_markup=workout_feedback_keyboard(workout_record.id),
        )

    logger.info("Morning push sent to user %d", user_id)


# ------------------------------------------------------------------ #
# Registration
# ------------------------------------------------------------------ #

def register_jobs(app: Application) -> None:
    """Register all scheduled jobs on the PTB JobQueue."""
    jq = app.job_queue
    if jq is None:
        logger.warning("JobQueue not available — install python-telegram-bot[job-queue]")
        return

    # Morning sync + push
    jq.run_daily(
        job_morning_push,
        time=time(hour=7, minute=0, tzinfo=BELGRADE_TZ),
        name="morning_push",
    )

    # Silent syncs
    for t in _SILENT_SYNC_TIMES:
        t_with_tz = time(hour=t.hour, minute=t.minute, tzinfo=BELGRADE_TZ)
        jq.run_daily(
            job_silent_sync,
            time=t_with_tz,
            name=f"silent_sync_{t.hour:02d}{t.minute:02d}",
        )

    logger.info(
        "Jobs registered: morning push 07:00, silent syncs 12:00/17:00/21:00 (Europe/Belgrade)"
    )
