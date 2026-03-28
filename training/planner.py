from __future__ import annotations

"""
AI-powered training planner using Claude.

Builds personalised weekly plans and single-session workouts
for running, cycling, swimming, and strength training.
The plan is tailored to the athlete's current fitness (Garmin)
and recovery state (WHOOP).
"""

import logging
from dataclasses import dataclass

import anthropic

from config import config

logger = logging.getLogger(__name__)

SPORTS = ("running", "cycling", "swimming", "strength")

_SPORT_LABELS = {
    "running": "бег",
    "cycling": "велосипед",
    "swimming": "плавание",
    "strength": "силовые тренировки",
}

_SYSTEM_PROMPT = """\
Ты — элитный тренер по выносливости и персональный фитнес-коуч. \
Ты специализируешься на беге, велосипеде, плавании и силовых тренировках. \
Ты анализируешь данные с носимых устройств Garmin и WHOOP и составляешь \
персонализированные тренировочные планы, основанные на текущем состоянии \
спортсмена. Отвечай на русском языке. \
Используй Markdown-форматирование для структуры ответа. \
Давай конкретные цифры: темп, пульсовые зоны, объём, интенсивность. \
Всегда учитывай данные восстановления при рекомендации интенсивности.\
"""


@dataclass
class AthleteContext:
    """Aggregated context passed to the AI planner."""

    # WHOOP recovery
    whoop_recovery_score: float | None = None  # 0–100
    whoop_hrv_ms: float | None = None
    whoop_resting_hr: float | None = None
    whoop_strain_today: float | None = None  # 0–21
    whoop_sleep_performance: float | None = None  # 0–100

    # Garmin fitness
    garmin_training_readiness: int | None = None  # 0–100
    garmin_vo2max: float | None = None
    garmin_steps_today: int | None = None
    garmin_body_battery: int | None = None  # 0–100

    # Recent activities (last 7 days) — list of dicts
    recent_activities: list[dict] | None = None

    # Weekly totals
    weekly_distance_km: float | None = None
    weekly_duration_h: float | None = None
    weekly_sport_breakdown: dict | None = None

    def to_prompt_text(self) -> str:
        lines = ["### Данные спортсмена\n"]

        if self.whoop_recovery_score is not None:
            lines.append(f"- **WHOOP Восстановление:** {self.whoop_recovery_score}%")
        if self.whoop_hrv_ms is not None:
            lines.append(f"- **HRV (WHOOP):** {self.whoop_hrv_ms} мс")
        if self.whoop_resting_hr is not None:
            lines.append(f"- **ЧСС покоя (WHOOP):** {self.whoop_resting_hr} уд/мин")
        if self.whoop_strain_today is not None:
            lines.append(f"- **Strain сегодня (WHOOP):** {self.whoop_strain_today:.1f}/21")
        if self.whoop_sleep_performance is not None:
            lines.append(f"- **Качество сна (WHOOP):** {self.whoop_sleep_performance}%")

        if self.garmin_training_readiness is not None:
            lines.append(
                f"- **Готовность к тренировке (Garmin):** {self.garmin_training_readiness}/100"
            )
        if self.garmin_vo2max is not None:
            lines.append(f"- **VO2max (Garmin):** {self.garmin_vo2max} мл/кг/мин")
        if self.garmin_body_battery is not None:
            lines.append(f"- **Body Battery (Garmin):** {self.garmin_body_battery}/100")
        if self.garmin_steps_today is not None:
            lines.append(f"- **Шаги сегодня:** {self.garmin_steps_today:,}")

        if self.weekly_distance_km is not None:
            lines.append(f"- **Объём за 7 дней:** {self.weekly_distance_km} км")
        if self.weekly_duration_h is not None:
            lines.append(f"- **Время тренировок за 7 дней:** {self.weekly_duration_h} ч")
        if self.weekly_sport_breakdown:
            breakdown = ", ".join(
                f"{k}: {v}" for k, v in self.weekly_sport_breakdown.items()
            )
            lines.append(f"- **Тренировки по видам:** {breakdown}")

        if self.recent_activities:
            lines.append("\n### Последние тренировки\n")
            for act in self.recent_activities[:5]:
                sport = act.get("activityType", {}).get("typeKey", "other")
                date = act.get("startTimeLocal", "")[:10]
                dist = act.get("distance", 0) or 0
                dur = act.get("duration", 0) or 0
                avg_hr = act.get("averageHR", "—")
                lines.append(
                    f"- {date} | {sport} | {dist/1000:.1f} км | "
                    f"{int(dur//60)} мин | ЧСС avg {avg_hr}"
                )

        return "\n".join(lines)


class TrainingPlanner:
    """Generates training plans using the Anthropic Claude API."""

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    async def generate_weekly_plan(
        self, sport: str, context: AthleteContext, goal: str = ""
    ) -> str:
        """Generate a full weekly training plan for the given sport."""
        sport_label = _SPORT_LABELS.get(sport, sport)
        goal_text = f"\n**Цель спортсмена:** {goal}" if goal else ""

        user_prompt = f"""\
{context.to_prompt_text()}
{goal_text}

Составь **недельный тренировочный план** по виду: **{sport_label}**.

Требования:
1. Учитывай текущее состояние восстановления и готовность к тренировкам.
2. Включи 5–7 тренировочных дней с конкретными заданиями.
3. Для каждой тренировки укажи:
   - Тип (восстановительная, базовая, интервальная, силовая и т.д.)
   - Объём/продолжительность
   - Интенсивность (пульсовая зона или % от FTP/темп/RPE)
   - Конкретное задание (например: «10 × 400 м в зоне 4 с отдыхом 90 с»)
4. Рекомендуй 1–2 дня восстановления / активного отдыха.
5. В конце — краткий комментарий тренера по текущему состоянию спортсмена.\
"""

        message = await self._client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text

    async def generate_single_session(
        self, sport: str, context: AthleteContext, session_type: str = "auto"
    ) -> str:
        """Generate a single workout session adapted to current recovery."""
        sport_label = _SPORT_LABELS.get(sport, sport)

        # Auto-select session type based on recovery
        if session_type == "auto":
            if context.whoop_recovery_score is not None:
                if context.whoop_recovery_score >= 67:
                    session_type = "высокоинтенсивная"
                elif context.whoop_recovery_score >= 34:
                    session_type = "умеренная"
                else:
                    session_type = "восстановительная"
            else:
                session_type = "базовая"

        user_prompt = f"""\
{context.to_prompt_text()}

Составь **одну тренировочную сессию** ({session_type}) по виду: **{sport_label}**.

Структура ответа:
1. **Разминка** — 10–15 мин (детально)
2. **Основная часть** — детальное задание с конкретными параметрами
3. **Заминка** — 10 мин
4. **Рекомендации по питанию и восстановлению** после тренировки
5. **Почему именно такая тренировка** — 2–3 предложения тренера\
"""

        message = await self._client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text

    async def analyze_recovery(self, context: AthleteContext) -> str:
        """Analyse the athlete's current recovery state and give recommendations."""
        user_prompt = f"""\
{context.to_prompt_text()}

Проведи **анализ восстановления** спортсмена:
1. Оцени текущее состояние по шкале (отличное / хорошее / удовлетворительное / низкое).
2. Определи ключевые факторы, влияющие на восстановление.
3. Дай **3–5 конкретных рекомендаций** по улучшению.
4. Укажи, **какие виды тренировок** сегодня оптимальны, а каких следует избегать.\
"""

        message = await self._client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=800,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text

    async def answer_question(
        self, question: str, context: AthleteContext
    ) -> str:
        """Free-form Q&A about training, recovery, or health."""
        user_prompt = f"""\
{context.to_prompt_text()}

**Вопрос спортсмена:** {question}\
"""

        message = await self._client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=800,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text


# Module-level singleton
planner = TrainingPlanner()
