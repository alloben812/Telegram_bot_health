from __future__ import annotations

"""
Sync handler — pulls data from Garmin and WHOOP,
stores it in the database, and shows a summary.

Garmin 429 avoidance: we use connect_cached() which reuses the stored
OAuth token instead of doing a fresh password login every time.
"""

import logging
from datetime import date

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.keyboards import SYNC_KB
from database.db import (
    get_garmin_oauth_token,
    get_garmin_password,
    get_user,
    get_whoop_token,
    update_garmin_oauth_token,
    upsert_daily_snapshot,
)

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

    # ------------------------------------------------------------------ #
    # Garmin
    # ------------------------------------------------------------------ #
    if action in ("garmin", "all"):
        garmin_pw = get_garmin_password(user) if user.garmin_email else None
        if not user.garmin_email or not garmin_pw:
            errors.append("⌚ Garmin не настроен (⚙️ Настройки → Garmin)")
        else:
            try:
                from integrations.garmin import GarminClient

                gc = GarminClient()
                cached_token = get_garmin_oauth_token(user)  # may be None on first run

                token_refreshed = await gc.connect_cached(
                    email=user.garmin_email,
                    password=garmin_pw,
                    token_b64=cached_token,
                )

                # Persist the new token so next sync reuses it (avoids 429)
                if token_refreshed and gc.fresh_token_b64:
                    await update_garmin_oauth_token(user_id, gc.fresh_token_b64)
                    logger.info("Saved fresh Garmin OAuth token for user %d", user_id)

                today = date.today()
                garmin_data = await gc.get_daily_summary(today)
                garmin_data["_weekly"] = await gc.get_weekly_summary()
                garmin_data["_activities"] = await gc.get_activities(0, 10)

            except Exception as exc:
                logger.error("Garmin sync error for user %d: %s", user_id, exc)
                err_msg = str(exc)
                if "429" in err_msg or "rate" in err_msg.lower():
                    errors.append(
                        "⌚ Garmin: лимит запросов (429). "
                        "Подожди 10–15 минут и попробуй снова."
                    )
                else:
                    errors.append(f"⌚ Garmin: {exc}")

    # ------------------------------------------------------------------ #
    # WHOOP
    # ------------------------------------------------------------------ #
    if action in ("whoop", "all"):
        whoop_token = get_whoop_token(user) if user.whoop_token_enc else None
        if not whoop_token:
            errors.append("💍 WHOOP не авторизован (⚙️ Настройки → WHOOP)")
        else:
            try:
                from integrations.whoop import WhoopClient

                wc = WhoopClient(user_id)
                wc.load_token(whoop_token)

                recovery = await wc.get_latest_recovery()
                sleep = await wc.get_latest_sleep()
                cycle = await wc.get_latest_cycle()
                whoop_data = {
                    "recovery": recovery or {},
                    "sleep": sleep or {},
                    "cycle": cycle or {},
                }
            except Exception as exc:
                logger.error("WHOOP sync error for user %d: %s", user_id, exc)
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
        steps_fmt = f"{steps:,}" if isinstance(steps, int) else str(steps)
        lines.append(
            "⌚ *Garmin сегодня:*\n"
            f"  Шаги: {steps_fmt}\n"
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
        cyc = whoop_data.get("cycle", {}).get("score", {})

        recovery_pct = rec.get("recovery_score", "—")
        hrv = rec.get("hrv_rmssd_milli", "—")
        rhr = rec.get("resting_heart_rate", "—")
        strain = cyc.get("strain", "—")
        sleep_perf = sl.get("sleep_performance_percentage", "—")

        emoji = (
            "🟢" if isinstance(recovery_pct, (int, float)) and recovery_pct >= 67
            else "🟡" if isinstance(recovery_pct, (int, float)) and recovery_pct >= 34
            else "🔴" if isinstance(recovery_pct, (int, float))
            else "⚪"
        )

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

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


def get_sync_handlers() -> list:
    return [CallbackQueryHandler(sync_callback, pattern=r"^sync:")]
