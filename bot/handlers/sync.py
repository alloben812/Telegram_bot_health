from __future__ import annotations

"""
Sync handler — pulls data from Garmin and WHOOP,
stores it in the database, and shows a summary.

Both sources are independent:
  Garmin  → GPS, distance, pace, power, cadence, elevation, steps, body battery
  WHOOP   → Strain, HRV, recovery score, SpO2, skin temp, sleep quality
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.keyboards import SYNC_KB
from config import config
from database.db import (
    get_garmin_oauth_token,
    get_garmin_password,
    get_user,
    get_whoop_token,
    save_garmin_activities,
    save_whoop_workouts,
    update_garmin_oauth_token,
    update_user_whoop_token,
    upsert_daily_snapshot,
)

logger = logging.getLogger(__name__)


def _format_garmin_error(exc: Exception) -> str:
    """Return a user-facing Garmin sync error."""
    user_message = getattr(exc, "user_message", None)
    if callable(user_message):
        return user_message()
    return str(exc)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _date_str(ts: str) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp string."""
    try:
        return (
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%d")
        )
    except Exception:
        return ts[:10]


async def _build_garmin_client(user):
    """Login to Garmin with cached session, return GarminClient.

    Priority:
    1. DB-stored garth token (works on Render where filesystem is ephemeral)
    2. File-based tokenstore cache (works locally)
    3. Full SSO login (last resort, risks 429)

    After successful login, the garth token is saved back to DB.
    """
    from integrations.garmin import GarminClient
    import garminconnect

    db_email = user.garmin_email
    db_password = get_garmin_password(user) if db_email else None
    email = db_email or config.GARMIN_EMAIL
    password = db_password or config.GARMIN_PASSWORD

    if not email or not password:
        raise RuntimeError(
            "Garmin не настроен. Для локального теста заполни "
            "GARMIN_EMAIL и GARMIN_PASSWORD в .env или настрой Garmin в боте."
        )

    gc = GarminClient()

    # Try DB-stored garth token first (critical for Render where no filesystem cache)
    db_token_b64 = get_garmin_oauth_token(user)
    if db_token_b64:
        try:
            client = garminconnect.Garmin(email, password)
            client.garth.loads(db_token_b64)
            # Verify the token works by fetching display name
            client.display_name = client.garth.profile["displayName"]
            client.full_name = client.garth.profile["fullName"]
            gc._client = client
            logger.info("Garmin: loaded session from DB token for %s", email)
            # Save refreshed token back
            fresh_b64 = client.garth.dumps()
            await update_garmin_oauth_token(user.id, fresh_b64)
            return gc
        except Exception as exc:
            logger.warning("Garmin: DB token login failed (%s), falling back", exc)

    # Fall back to file cache / full login
    def _login():
        return gc._create_client_for_user(email, password)

    loop = asyncio.get_event_loop()
    gc._client = await loop.run_in_executor(None, _login)

    # Save token to DB for next time (especially important on Render)
    try:
        fresh_b64 = gc._client.garth.dumps()
        await update_garmin_oauth_token(user.id, fresh_b64)
        logger.info("Garmin: saved fresh token to DB for %s", email)
    except Exception as exc:
        logger.warning("Garmin: failed to save token to DB: %s", exc)

    return gc


async def _build_whoop_client(user, user_id: int):
    """Load WHOOP token, return WhoopClient."""
    from integrations.whoop import WhoopClient

    whoop_token = get_whoop_token(user) if user.whoop_token_enc else None
    if not whoop_token:
        raise RuntimeError("WHOOP не авторизован (⚙️ Настройки → WHOOP)")

    wc = WhoopClient(user_id)
    wc.load_token(whoop_token)
    return wc


async def _persist_whoop_token(user_id: int) -> None:
    """Save refreshed WHOOP token back to DB if it was updated in memory."""
    from integrations.whoop import _TOKEN_STORE

    fresh = _TOKEN_STORE.get(user_id)
    if fresh:
        await update_user_whoop_token(user_id, {
            k: v for k, v in fresh.items() if k != "expires_at"
        })


# ------------------------------------------------------------------ #
# Sync menu
# ------------------------------------------------------------------ #

async def sync_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔄 *Синхронизация данных*\n\nВыбери источник:",
        parse_mode="Markdown",
        reply_markup=SYNC_KB,
    )


# ------------------------------------------------------------------ #
# Regular sync (today's snapshot)
# ------------------------------------------------------------------ #

async def sync_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Daily snapshot sync for Garmin and/or WHOOP."""
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]  # garmin | whoop | all

    user_id = update.effective_user.id
    user = await get_user(user_id)

    if not user:
        await query.edit_message_text("❌ Пользователь не найден. Введи /start")
        return

    await query.edit_message_text("⏳ Синхронизирую данные…")

    garmin_data: dict | None = None
    whoop_data: dict | None = None
    errors: list[str] = []

    # ---- Garmin: daily stats + save today's activities ----
    if action in ("garmin", "all"):
        try:
            gc = await _build_garmin_client(user)
            today = date.today()
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
        except Exception as exc:
            logger.error("Garmin sync error: %s", exc)
            errors.append(f"⌚ Garmin: {_format_garmin_error(exc)}")

    # ---- WHOOP: latest cycle/recovery/sleep ----
    if action in ("whoop", "all"):
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
            else:
                errors.append("💍 WHOOP: данных пока нет (устройство не синхронизировалось?)")
        except Exception as exc:
            logger.error("WHOOP sync error: %s", exc)
            errors.append(f"💍 WHOOP: {exc}")

    # ------------------------------------------------------------------ #
    # Save & respond
    # ------------------------------------------------------------------ #
    if garmin_data or whoop_data:
        await upsert_daily_snapshot(
            user_id=user_id,
            snapshot_date=date.today().isoformat(),
            garmin_data=garmin_data,
            whoop_data=whoop_data,
        )

    lines = ["✅ *Синхронизация завершена*\n"]

    if garmin_data:
        steps = garmin_data.get("totalSteps", "—")
        cal = garmin_data.get("activeKilocalories", "—")
        stress = garmin_data.get("averageStressLevel", "—")
        today_acts = garmin_data.get("_activities", [])
        steps_fmt = f"{steps:,}" if isinstance(steps, int) else str(steps)

        # Training readiness and body battery
        tr_data = garmin_data.get("_training_readiness") or {}
        tr_score = tr_data.get("score") or tr_data.get("trainingReadiness")
        bb_data = garmin_data.get("_body_battery") or []
        bb_score = None
        if bb_data and isinstance(bb_data, list):
            last_bb = bb_data[-1] if bb_data else {}
            bb_score = last_bb.get("bodyBatteryLevel") or last_bb.get("charged")

        garmin_lines = [
            "⌚ *Garmin сегодня:*",
            f"  Шаги: {steps_fmt}",
            f"  Активные ккал: {cal}",
            f"  Средний стресс: {stress}",
        ]
        if tr_score is not None:
            garmin_lines.append(f"  Готовность: {tr_score}/100")
        if bb_score is not None:
            garmin_lines.append(f"  Body Battery: {bb_score}/100")
        garmin_lines.append(f"  Тренировок сегодня: {len(today_acts)}")
        lines.append("\n".join(garmin_lines) + "\n")

        weekly = garmin_data.get("_weekly", {})
        if weekly:
            lines.append(
                f"  Активностей за 7 дней: {weekly.get('total_activities', '—')}\n"
                f"  Дистанция за 7 дней: {weekly.get('total_distance_km', '—')} км\n"
            )

    if whoop_data:
        rec = whoop_data.get("recovery", {}).get("score", {})
        sl = whoop_data.get("sleep", {}).get("score", {})
        cyc = whoop_data.get("cycle", {}).get("score", {})

        recovery_pct = rec.get("recovery_score", "—")
        hrv = rec.get("hrv_rmssd_milli", "—")
        rhr = rec.get("resting_heart_rate", "—")
        strain = cyc.get("strain", "—")
        sleep_perf = sl.get("sleep_performance_percentage", "—")
        spo2 = rec.get("spo2_percentage")
        skin_temp = rec.get("skin_temp_celsius")
        resp_rate = sl.get("respiratory_rate")

        emoji = (
            "🟢" if isinstance(recovery_pct, (int, float)) and recovery_pct >= 67
            else "🟡" if isinstance(recovery_pct, (int, float)) and recovery_pct >= 34
            else "🔴" if isinstance(recovery_pct, (int, float))
            else "⚪"
        )

        def _fmt(v, decimals=1):
            return round(v, decimals) if isinstance(v, float) else v

        body = (
            f"💍 *WHOOP сегодня:*\n"
            f"  {emoji} Recovery: {_fmt(recovery_pct)}%\n"
            f"  HRV: {_fmt(hrv)} мс  ЧСС покоя: {_fmt(rhr)}\n"
            f"  Strain: {_fmt(strain)}/21\n"
            f"  Сон: {_fmt(sleep_perf)}%\n"
        )
        if spo2:
            body += f"  SpO2: {_fmt(spo2)}%\n"
        if skin_temp:
            body += f"  Т° кожи: {_fmt(skin_temp)}°C\n"
        if resp_rate:
            body += f"  Дыхание: {_fmt(resp_rate)} вд/мин\n"
        w_count = len(whoop_data.get("workouts", []))
        if w_count:
            body += f"  Тренировок (WHOOP): {w_count}\n"
        lines.append(body)

    if errors:
        lines.append("⚠️ *Ошибки:*\n" + "\n".join(errors))

    if not garmin_data and not whoop_data:
        lines = ["❌ Не удалось получить данные.\n"] + errors

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


# ------------------------------------------------------------------ #
# WHOOP 4-week history
# ------------------------------------------------------------------ #

async def sync_whoop_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pull last 28 days of WHOOP data: daily snapshots + individual workouts."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = await get_user(user_id)

    if not user:
        await query.edit_message_text("❌ Пользователь не найден. Введи /start")
        return

    try:
        wc = await _build_whoop_client(user, user_id)
    except RuntimeError as exc:
        await query.edit_message_text(str(exc))
        return

    await query.edit_message_text("⏳ Загружаю историю WHOOP за 4 недели…")

    try:
        await query.edit_message_text("⏳ WHOOP: циклы (strain/пульс)…")
        cycles = await wc.get_cycles_since(days=28)

        await query.edit_message_text("⏳ WHOOP: восстановление (HRV/recovery)…")
        recoveries = await wc.get_recoveries_since(days=28)

        await query.edit_message_text("⏳ WHOOP: сон…")
        sleeps = await wc.get_sleeps_since(days=28)

        await query.edit_message_text("⏳ WHOOP: тренировки…")
        workouts = await wc.get_workouts_since(days=28)

        await _persist_whoop_token(user_id)

        # Index all collections by calendar date
        def _index_by_date(records: list[dict], ts_keys: list[str]) -> dict[str, dict]:
            out: dict[str, dict] = {}
            for r in records:
                for k in ts_keys:
                    ts = r.get(k)
                    if ts:
                        out[_date_str(ts)] = r
                        break
            return out

        cycle_by_date = _index_by_date(cycles, ["start"])
        recovery_by_date = _index_by_date(recoveries, ["created_at", "updated_at"])
        sleep_by_date = _index_by_date(sleeps, ["end", "start"])

        workout_by_date: dict[str, list] = {}
        for w in workouts:
            ts = w.get("start") or ""
            if ts:
                d = _date_str(ts)
                workout_by_date.setdefault(d, []).append(w)

        all_dates = sorted(
            set(cycle_by_date) | set(recovery_by_date) | set(sleep_by_date) | set(workout_by_date),
            reverse=True,
        )

        saved_days = 0
        for day in all_dates:
            await upsert_daily_snapshot(
                user_id=user_id,
                snapshot_date=day,
                whoop_data={
                    "recovery": recovery_by_date.get(day, {}),
                    "sleep": sleep_by_date.get(day, {}),
                    "cycle": cycle_by_date.get(day, {}),
                    "workouts": workout_by_date.get(day, []),
                },
            )
            saved_days += 1

        inserted_workouts = await save_whoop_workouts(user_id, workouts)

        summary = (
            f"✅ *WHOOP история за 4 недели:*\n\n"
            f"⚡ Дней со strain: {len(cycle_by_date)} из 28\n"
            f"💚 Дней с recovery/HRV: {len(recovery_by_date)}\n"
            f"😴 Ночей со сном: {len(sleep_by_date)}\n"
            f"🏋️ Тренировок получено: {len(workouts)}"
            + (f" (+{inserted_workouts} новых)" if inserted_workouts else " (все уже в базе)") + "\n\n"
            f"_WHOOP: физиологические данные (strain, HRV, recovery, пульсовые зоны)_\n"
            f"_Garmin: механические данные (GPS, темп, мощность) → ⌚ История Garmin 4 недели_"
        )

        diag: list[str] = []
        if not recoveries:
            diag.append("💚 Recovery/HRV: нет данных — WHOOP не записал восстановление")
        if not sleeps:
            diag.append("😴 Сон: нет данных — носи WHOOP ночью и синкай приложение")
        if not workouts:
            diag.append("🏋️ Тренировки WHOOP: 0 — нажимай Start в приложении WHOOP перед тренировкой")
        if diag:
            summary += "\n\n*Что отсутствует:*\n" + "\n".join(diag)

        await query.edit_message_text(summary, parse_mode="Markdown", reply_markup=SYNC_KB)

    except Exception as exc:
        logger.error("WHOOP history sync error: %s", exc)
        await query.edit_message_text(
            f"❌ Ошибка загрузки истории WHOOP: {exc}",
            reply_markup=SYNC_KB,
        )


# ------------------------------------------------------------------ #
# Garmin 4-week history
# ------------------------------------------------------------------ #

async def sync_garmin_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pull last 28 days of Garmin activities and save to Activity table."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = await get_user(user_id)

    if not user:
        await query.edit_message_text("❌ Пользователь не найден. Введи /start")
        return

    try:
        gc = await _build_garmin_client(user)
    except RuntimeError as exc:
        await query.edit_message_text(str(exc))
        return

    await query.edit_message_text("⏳ Загружаю историю Garmin за 4 недели…")

    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=28)

        await query.edit_message_text("⏳ Garmin: загружаю все активности за 28 дней…")
        activities = await gc.get_activities_by_date(start_date, end_date)

        # Count by sport
        sport_counts: dict[str, int] = {}
        for a in activities:
            key = (
                a.get("activityType", {}).get("typeKey", "other")
                if isinstance(a.get("activityType"), dict)
                else "other"
            )
            sport_counts[key] = sport_counts.get(key, 0) + 1

        inserted = await save_garmin_activities(user_id, activities)

        # Also update daily snapshots with Garmin stats for past 28 days
        await query.edit_message_text("⏳ Garmin: обновляю суточные показатели…")
        saved_days = 0
        current = end_date
        while current >= start_date:
            try:
                daily = await gc.get_daily_summary(current)
                if daily:
                    await upsert_daily_snapshot(
                        user_id=user_id,
                        snapshot_date=current.isoformat(),
                        garmin_data=daily,
                    )
                    saved_days += 1
            except Exception as day_exc:
                logger.debug("Garmin daily summary %s: %s", current, day_exc)
            current -= timedelta(days=1)

        # Build sport breakdown text
        sport_lines = "\n".join(
            f"  {k}: {v}" for k, v in sorted(sport_counts.items(), key=lambda x: -x[1])
        ) or "  (нет данных)"

        await query.edit_message_text(
            f"✅ *История Garmin загружена:*\n\n"
            f"🏋️ Тренировок получено: {len(activities)}\n"
            f"✅ Новых сохранено: {inserted}\n"
            f"📅 Суточных снимков: {saved_days}\n\n"
            f"*Разбивка по видам:*\n{sport_lines}",
            parse_mode="Markdown",
            reply_markup=SYNC_KB,
        )

    except Exception as exc:
        logger.error("Garmin history sync error: %s", exc)
        await query.edit_message_text(
            f"❌ Ошибка загрузки истории Garmin: {exc}",
            reply_markup=SYNC_KB,
        )


# ------------------------------------------------------------------ #
# Handler registration
# ------------------------------------------------------------------ #

def get_sync_handlers() -> list:
    return [
        CallbackQueryHandler(sync_whoop_history, pattern=r"^sync:whoop_history$"),
        CallbackQueryHandler(sync_garmin_history, pattern=r"^sync:garmin_history$"),
        CallbackQueryHandler(sync_callback, pattern=r"^sync:"),
    ]
