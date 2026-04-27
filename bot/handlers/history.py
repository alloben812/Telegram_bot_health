from __future__ import annotations

"""7-day history handler."""

import json
import logging
from datetime import date

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from bot.keyboards import MAIN_MENU_KB
from database.db import get_recent_recommendations, get_planned_workout

logger = logging.getLogger(__name__)

_CONFIDENCE = {"low": "🔴", "medium": "🟡", "high": "🟢"}
_SPORT_EMOJI = {
    "run": "🏃", "bike": "🚴", "swim": "🏊", "strength": "💪",
    "walk": "🚶", "mobility": "🧘", "recovery": "💆", "rest": "😴", "other": "🏋️",
}


async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    recs = await get_recent_recommendations(user_id, days=7)

    if not recs:
        await update.message.reply_text(
            "📭 История пуста. Нажми *📅 Сегодня* чтобы получить первую рекомендацию.",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU_KB,
        )
        return

    lines = ["*📆 История за 7 дней*\n"]
    for rec in recs:
        conf = _CONFIDENCE.get(rec.confidence or "", "")
        workout = await get_planned_workout(user_id, rec.date)
        sport_line = ""
        if workout:
            emoji = _SPORT_EMOJI.get(workout.sport, "🏋️")
            dur = f" {workout.duration_minutes} мин" if workout.duration_minutes else ""
            sport_line = f"\n  {emoji} {workout.title}{dur}"

        reasoning = json.loads(rec.reasoning_json) if rec.reasoning_json else []
        reason_short = reasoning[0] if reasoning else ""

        lines.append(
            f"*{rec.date}* {conf} {rec.readiness_score}/100\n"
            f"  {rec.main_recommendation}{sport_line}"
            + (f"\n  _{reason_short}_" if reason_short else "")
        )
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n…"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MAIN_MENU_KB)


def get_history_handlers():
    return [
        CommandHandler("history", history_handler),
        MessageHandler(filters.Regex(r"^📆 История$"), history_handler),
    ]
