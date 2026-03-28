"""
Sync handler — pulls data from Garmin and WHOOP,
stores it in the database, and shows a summary.
"""

from __future__ import annotations
import logging
from datetime import date, datetime, timezone

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.keyboards import SYNC_KB
from database.db import get_garmin_password, get_user, get_whoop_token, upsert_daily_snapshot

logger = logging.getLogger(__name__)


async def sync_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔄 *Синхронизация данных*\n\nВыбери источник:",
        parse_mode="Markdown",
        reply_markup=SYNC_KB,
    )


async def sync_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    # ---- Garmin ----
    if action in ("garmin", "all"):
        garmin_pw = get_garmin_password(user) if user.garmin_email else None
        if not user.garmin_email or not garmin_pw:
            errors.append("⌚ Garmin не настроен (⚙️ Настройки → Garmin)")
        else:
            try:
                from integrations.garmin import GarminClient
                import garminconnect
                import asyncio

                gc = GarminClient()
                _email = user.garmin_email
                _pw = garmin_pw  # already decrypted plaintext

                def _login():
                    c = garminconnect.Garmin(_email, _pw)
                    c.login()
                    return c

                loop = asyncio.get_event_loop()
                _client = await loop.run_in_executor(None, _login)
                gc._client = _client

                today = date.today()
                garmin_data = await gc.get_daily_summary(today)
                garmin_data["_weekly"] = await gc.get_weekly_summary()
                garmin_data["_activities"] = await gc.get_activities(0, 10)
            except Exception as exc:
                logger.error("Garmin sync error: %s", exc)
                errors.append(f"⌚ Garmin: {exc}")

    # ---- WHOOP ----
    if action in ("whoop", "all"):
        whoop_token = get_whoop_token(user) if user.whoop_token_enc else None
        if not whoop_token:
            errors.append("💍 WHOOP не авторизован (⚙️ Настройки → WHOOP)")
        else:
            try:
                from integrations.whoop import WhoopClient
                wc = WhoopClient(user_id)
                wc.load_token(whoop_token)  # decrypted token dict

                recovery = await wc.get_latest_recovery()
                sleep = await wc.get_latest_sleep()
                cycle = await wc.get_latest_cycle()

                if recovery or sleep or cycle:
                    whoop_data = {
                        "recovery": recovery or {},
                        "sleep": sleep or {},
                        "cycle": cycle or {},
                    }
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
        lines.append(
            "⌚ *Garmin сегодня:*\n"
            f"  Шаги: {steps:,}\n"
            f"  Активные ккал: {cal}\n"
            f"  Средний стресс: {stress}\n"
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
        cycle = whoop_data.get("cycle", {}).get("score", {})

        recovery_pct = rec.get("recovery_score", "—")
        hrv = rec.get("hrv_rmssd_milli", "—")
        rhr = rec.get("resting_heart_rate", "—")
        strain = cycle.get("strain", "—")
        sleep_perf = sl.get("sleep_performance_percentage", "—")

        # Round numeric values for display
        if isinstance(hrv, float):
            hrv = round(hrv, 1)
        if isinstance(rhr, float):
            rhr = round(rhr, 1)
        if isinstance(strain, float):
            strain = round(strain, 1)
        if isinstance(recovery_pct, float):
            recovery_pct = round(recovery_pct, 1)
        if isinstance(sleep_perf, float):
            sleep_perf = round(sleep_perf, 1)

        # Recovery emoji
        if isinstance(recovery_pct, (int, float)):
            emoji = "🟢" if recovery_pct >= 67 else ("🟡" if recovery_pct >= 34 else "🔴")
        else:
            emoji = "⚪"

        lines.append(
            f"💍 *WHOOP сегодня:*\n"
            f"  {emoji} Восстановление: {recovery_pct}%\n"
            f"  HRV: {hrv} мс\n"
            f"  ЧСС покоя: {rhr} уд/мин\n"
            f"  Strain: {strain}\n"
            f"  Качество сна: {sleep_perf}%\n"
        )

    if errors:
        lines.append("⚠️ *Ошибки:*\n" + "\n".join(errors))

    if not garmin_data and not whoop_data:
        lines = ["❌ Не удалось получить данные.\n"] + errors

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


async def sync_whoop_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pull last 30 days of WHOOP data and create a DailySnapshot per day."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = await get_user(user_id)

    if not user:
        await query.edit_message_text("❌ Пользователь не найден. Введи /start")
        return

    whoop_token = get_whoop_token(user) if user.whoop_token_enc else None
    if not whoop_token:
        await query.edit_message_text("💍 WHOOP не авторизован. Подключи через ⚙️ Настройки.")
        return

    await query.edit_message_text("⏳ Загружаю историю WHOOP за 30 дней…")

    try:
        from integrations.whoop import WhoopClient
        from datetime import timedelta
        wc = WhoopClient(user_id)
        wc.load_token(whoop_token)

        end_dt = datetime.now(tz=timezone.utc)
        start_dt = end_dt - timedelta(days=30)

        recoveries = await wc.get_recovery_collection(start_date=start_dt, end_date=end_dt)
        sleeps = await wc.get_sleep_collection(limit=25)
        cycles = await wc.get_cycle_collection(limit=25)
        workouts = await wc.get_workout_collection(limit=25)

        def _date_str(ts: str) -> str:
            """Extract YYYY-MM-DD from an ISO timestamp string."""
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                return ts[:10]

        # Index by date
        recovery_by_date: dict[str, dict] = {}
        for r in recoveries:
            ts = r.get("created_at") or r.get("updated_at") or ""
            if ts:
                recovery_by_date[_date_str(ts)] = r

        sleep_by_date: dict[str, dict] = {}
        for s in sleeps:
            ts = s.get("end") or s.get("start") or ""
            if ts:
                sleep_by_date[_date_str(ts)] = s

        cycle_by_date: dict[str, dict] = {}
        for c in cycles:
            ts = c.get("start") or ""
            if ts:
                cycle_by_date[_date_str(ts)] = c

        workout_by_date: dict[str, list] = {}
        for w in workouts:
            ts = w.get("start") or ""
            if ts:
                d = _date_str(ts)
                workout_by_date.setdefault(d, []).append(w)

        all_dates = sorted(
            set(recovery_by_date) | set(sleep_by_date) | set(cycle_by_date) | set(workout_by_date),
            reverse=True,
        )

        saved = 0
        for day in all_dates:
            whoop_data = {
                "recovery": recovery_by_date.get(day, {}),
                "sleep": sleep_by_date.get(day, {}),
                "cycle": cycle_by_date.get(day, {}),
                "workouts": workout_by_date.get(day, []),
            }
            await upsert_daily_snapshot(
                user_id=user_id,
                snapshot_date=day,
                whoop_data=whoop_data,
            )
            saved += 1

        await query.edit_message_text(
            f"✅ История WHOOP загружена: {saved} дней сохранено в базе.\n\n"
            "Теперь 📊 Статистика покажет исторические данные.",
            reply_markup=SYNC_KB,
        )

    except Exception as exc:
        logger.error("WHOOP history sync error: %s", exc)
        await query.edit_message_text(
            f"❌ Ошибка загрузки истории WHOOP: {exc}",
            reply_markup=SYNC_KB,
        )


def get_sync_handlers() -> list:
    return [
        CallbackQueryHandler(sync_whoop_history, pattern=r"^sync:whoop_history$"),
        CallbackQueryHandler(sync_callback, pattern=r"^sync:"),
    ]
