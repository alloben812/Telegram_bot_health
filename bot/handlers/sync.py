"""
Sync handler — pulls data from Garmin and WHOOP,
stores it in the database, and shows a summary.

Both sources are independent:
  Garmin  → GPS, distance, pace, power, cadence, elevation, steps, body battery
  WHOOP   → Strain, HRV, recovery score, SpO2, skin temp, sleep quality
"""

from __future__ import annotations
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.keyboards import SYNC_KB
from database.db import (
    get_garmin_password,
    get_user,
    get_whoop_token,
    save_garmin_activities,
    save_whoop_workouts,
    update_user_whoop_token,
    upsert_daily_snapshot,
)

logger = logging.getLogger(__name__)


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
    """Login to Garmin with cached session, return GarminClient."""
    from integrations.garmin import GarminClient

    garmin_pw = get_garmin_password(user) if user.garmin_email else None
    if not user.garmin_email or not garmin_pw:
        raise RuntimeError("Garmin не настроен (⚙️ Настройки → Garmin)")

    gc = GarminClient()
    email, pw = user.garmin_email, garmin_pw

    def _login():
        return gc._create_client_for_user(email, pw)

    loop = asyncio.get_event_loop()
    gc._client = await loop.run_in_executor(None, _login)
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
        except Exception as exc:
            logger.error("Garmin sync error: %s", exc)
            errors.append(f"⌚ Garmin: {exc}")

    # ---- WHOOP: latest cycle/recovery/sleep ----
    if action in ("whoop", "all"):
        try:
            wc = await _build_whoop_client(user, user_id)

            recovery = await wc.get_latest_recovery()
            sleep = await wc.get_latest_sleep()
            cycle = await wc.get_latest_cycle()
            # Also grab today's workouts if any
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

    # Save snapshot
    if garmin_data or whoop_data:
        await upsert_daily_snapshot(
            user_id=user_id,
            snapshot_date=date.today().isoformat(),
            garmin_data=garmin_data,
            whoop_data=whoop_data,
        )

    # Build summary message
    lines = ["✅ *Синхронизация завершена*\n"]

    if garmin_data:
        steps = garmin_data.get("totalSteps", "—")
        cal = garmin_data.get("activeKilocalories", "—")
        stress = garmin_data.get("averageStressLevel", "—")
        today_acts = garmin_data.get("_activities", [])
        lines.append(
            "⌚ *Garmin сегодня:*\n"
            f"  Шаги: {steps:,}\n"
            f"  Активные ккал: {cal}\n"
            f"  Средний стресс: {stress}\n"
            f"  Тренировок сегодня: {len(today_acts)}\n"
        )
        weekly = garmin_data.get("_weekly", {})
        if weekly:
            lines.append(
                f"  Активностей за 7 дней: {weekly.get('total_activities', '—')}\n"
                f"  Дистанция за 7 дней: {weekly.get('total_distance_km', '—')} км\n"
            )

    if whoop_data:
        rec = whoop_data.get("recovery", {}).get("score", {})
        sl = whoop_data.get("sleep", {}).get("score", {})
        cycle_s = whoop_data.get("cycle", {}).get("score", {})

        recovery_pct = rec.get("recovery_score", "—")
        hrv = rec.get("hrv_rmssd_milli", "—")
        rhr = rec.get("resting_heart_rate", "—")
        strain = cycle_s.get("strain", "—")
        sleep_perf = sl.get("sleep_performance_percentage", "—")
        spo2 = rec.get("spo2_percentage")
        skin_temp = rec.get("skin_temp_celsius")
        resp_rate = sl.get("respiratory_rate")

        for val in [hrv, rhr, strain, recovery_pct, sleep_perf]:
            pass  # round in display below

        def _fmt(v, decimals=1):
            return round(v, decimals) if isinstance(v, float) else v

        emoji = (
            "🟢" if isinstance(recovery_pct, (int, float)) and recovery_pct >= 67
            else "🟡" if isinstance(recovery_pct, (int, float)) and recovery_pct >= 34
            else "🔴" if isinstance(recovery_pct, (int, float))
            else "⚪"
        )

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

        # Build diagnostic lines
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
