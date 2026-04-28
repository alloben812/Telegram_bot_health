from __future__ import annotations

"""
AI-powered training planner.

Uses AIProvider abstraction — no direct dependency on any specific AI SDK.
The default provider is OpenAI (gpt-4o); swap via ai.set_provider().
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError

from ai.provider import AIProvider
from ai.schemas import DailyRecommendation
from training.hr_zones import HRZones

logger = logging.getLogger(__name__)

SPORTS = ("run", "bike", "swim", "strength")

_SPORT_LABELS = {
    "run": "бег",
    "bike": "велосипед",
    "swim": "плавание",
    "strength": "силовые тренировки",
    "hiit": "HIIT",
    "walk": "ходьба",
    "mobility": "мобильность/йога",
    "other": "другое",
    "rest": "отдых",
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

_DAY_NAMES_RU = {
    0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг",
    4: "Пятница", 5: "Суббота", 6: "Воскресенье",
}

_TRAINING_DAY_LABELS = {
    "mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
    "fri": "Пт", "sat": "Сб", "sun": "Вс",
}


@dataclass
class AthleteContext:
    """Aggregated athlete data passed to the AI planner."""

    # WHOOP recovery (today)
    whoop_recovery_score: Optional[float] = None  # 0–100
    whoop_hrv_ms: Optional[float] = None
    whoop_resting_hr: Optional[float] = None
    whoop_strain_today: Optional[float] = None  # 0–21
    whoop_sleep_performance: Optional[float] = None  # 0–100
    whoop_spo2: Optional[float] = None
    whoop_skin_temp: Optional[float] = None
    whoop_respiratory_rate: Optional[float] = None

    # WHOOP 7-day trends
    hrv_7d_avg: Optional[float] = None
    sleep_7d_avg: Optional[float] = None

    # Trends (computed from recent snapshots)
    recovery_trend: Optional[str] = None  # "improving" / "stable" / "declining"
    strain_7d_avg: Optional[float] = None
    weekly_strain_total: Optional[float] = None
    sleep_debt_h: Optional[float] = None  # negative = debt, positive = surplus

    # Garmin (None while on cooldown — planner works without it)
    garmin_training_readiness: Optional[int] = None  # 0–100
    garmin_vo2max: Optional[float] = None
    garmin_steps_today: Optional[int] = None
    garmin_body_battery: Optional[int] = None  # 0–100
    garmin_stress_avg: Optional[int] = None   # 0–100
    garmin_active_calories: Optional[int] = None

    # Sleep duration from WHOOP
    whoop_sleep_duration_h: Optional[float] = None

    # Weekly load by canonical sport type
    # e.g. {"run": {"count": 3, "duration_min": 120, "distance_km": 25.5}}
    weekly_load_by_sport: Optional[dict] = None
    weekly_load_detail: Optional[list] = None  # prompt-ready bullet lines

    # Canonical sport types completed today, e.g. ["run"]
    completed_today: Optional[list] = None

    # Recent activities from DB (normalized format)
    recent_activities_db: Optional[list] = None

    # HR zones computed from max_hr in training profile
    hr_zones: Optional[HRZones] = None

    # User profile / goal
    goal_label: Optional[str] = None
    goal_distance_km: Optional[float] = None
    goal_target_time_min: Optional[int] = None
    available_training_days: Optional[list] = None  # e.g. ["Пн", "Вт", "Чт", "Сб"]
    max_run_days_per_week: Optional[int] = None
    strength_days_per_week: Optional[int] = None
    day_of_week: Optional[str] = None  # e.g. "Понедельник"

    # Legacy fields kept for handlers that build context manually
    recent_activities: Optional[list] = None
    weekly_distance_km: Optional[float] = None
    weekly_duration_h: Optional[float] = None

    def to_prompt_text(self) -> str:
        lines = []

        # Athlete profile section (goal, schedule, day of week)
        profile_lines = []
        if self.goal_label:
            profile_lines.append(f"- **Цель:** {self.goal_label}")
            if self.goal_distance_km:
                profile_lines.append(f"- **Дистанция цели:** {self.goal_distance_km} км")
            if self.goal_target_time_min:
                h, m = divmod(self.goal_target_time_min, 60)
                time_str = f"{h}:{m:02d}" if h else f"{m} мин"
                profile_lines.append(f"- **Целевое время:** {time_str}")
        if self.available_training_days:
            days_str = ", ".join(self.available_training_days)
            profile_lines.append(f"- **Дни тренировок:** {days_str} ({len(self.available_training_days)} дней/нед)")
        if self.max_run_days_per_week is not None:
            profile_lines.append(f"- **Беговых дней/нед:** {self.max_run_days_per_week}")
        if self.strength_days_per_week is not None:
            profile_lines.append(f"- **Силовых дней/нед:** {self.strength_days_per_week}")
        if self.day_of_week:
            profile_lines.append(f"- **Сегодня:** {self.day_of_week}")

        if profile_lines:
            lines.append("### Профиль спортсмена\n")
            lines.extend(profile_lines)
            lines.append("")

        lines.append("### Данные спортсмена\n")

        if self.whoop_recovery_score is not None:
            lines.append(f"- **WHOOP Восстановление:** {self.whoop_recovery_score}%")
        if self.whoop_hrv_ms is not None:
            hrv_trend = ""
            if self.hrv_7d_avg:
                delta = self.whoop_hrv_ms - self.hrv_7d_avg
                sign = "+" if delta >= 0 else ""
                hrv_trend = f" (среднее 7д: {self.hrv_7d_avg} мс, сегодня {sign}{delta:.0f})"
            lines.append(f"- **HRV (WHOOP):** {self.whoop_hrv_ms} мс{hrv_trend}")
        if self.whoop_resting_hr is not None:
            lines.append(f"- **ЧСС покоя:** {self.whoop_resting_hr} уд/мин")
        if self.whoop_strain_today is not None:
            lines.append(f"- **Strain сегодня:** {self.whoop_strain_today:.1f}/21")
        if self.whoop_sleep_performance is not None:
            sleep_trend = ""
            if self.sleep_7d_avg:
                sleep_trend = f" (среднее 7д: {self.sleep_7d_avg}%)"
            lines.append(f"- **Качество сна:** {self.whoop_sleep_performance}%{sleep_trend}")
        if self.whoop_spo2 is not None:
            lines.append(f"- **SpO2:** {self.whoop_spo2}%")
        if self.whoop_skin_temp is not None:
            lines.append(f"- **Т° кожи:** {self.whoop_skin_temp}°C")
        if self.whoop_respiratory_rate is not None:
            lines.append(f"- **Частота дыхания:** {self.whoop_respiratory_rate} вд/мин")

        if self.whoop_sleep_duration_h is not None:
            lines.append(f"- **Продолжительность сна:** {self.whoop_sleep_duration_h:.1f} ч")

        if self.garmin_training_readiness is not None:
            lines.append(f"- **Готовность (Garmin):** {self.garmin_training_readiness}/100")
        if self.garmin_stress_avg is not None:
            lines.append(f"- **Стресс (Garmin):** {self.garmin_stress_avg}/100")
        if self.garmin_active_calories is not None:
            lines.append(f"- **Активные калории (Garmin):** {self.garmin_active_calories} ккал")
        if self.garmin_vo2max is not None:
            lines.append(f"- **VO2max (Garmin):** {self.garmin_vo2max} мл/кг/мин")
        if self.garmin_body_battery is not None:
            lines.append(f"- **Body Battery:** {self.garmin_body_battery}/100")
        if self.garmin_steps_today is not None:
            lines.append(f"- **Шаги сегодня:** {self.garmin_steps_today:,}")

        if self.hr_zones:
            lines.extend(self.hr_zones.to_prompt_lines())

        # Trends section
        trend_lines = []
        if self.recovery_trend:
            arrow = {"improving": "↗", "stable": "→", "declining": "↘"}.get(
                self.recovery_trend, "→"
            )
            label = {"improving": "улучшается", "stable": "стабильно", "declining": "снижается"}.get(
                self.recovery_trend, self.recovery_trend
            )
            trend_lines.append(f"- **Тренд восстановления:** {arrow} {label}")
        if self.strain_7d_avg is not None:
            trend_lines.append(f"- **Средний strain за 7д:** {self.strain_7d_avg:.1f}/21")
        if self.weekly_strain_total is not None:
            trend_lines.append(f"- **Суммарный strain за 7д:** {self.weekly_strain_total:.1f}")
        if self.sleep_debt_h is not None:
            if self.sleep_debt_h < 0:
                trend_lines.append(f"- **Недосып за 7д:** {abs(self.sleep_debt_h):.1f} ч")
            elif self.sleep_debt_h > 0:
                trend_lines.append(f"- **Избыток сна за 7д:** {self.sleep_debt_h:.1f} ч")
        if trend_lines:
            lines.append("\n### Тренды за 7 дней\n")
            lines.extend(trend_lines)

        if self.completed_today:
            lines.append(f"- **Выполнено сегодня:** {', '.join(self.completed_today)}")

        if self.weekly_load_detail:
            lines.append("\n### Нагрузка за 7 дней\n")
            lines.extend(self.weekly_load_detail)
        elif self.weekly_distance_km is not None:
            lines.append(f"- **Объём за 7 дней:** {self.weekly_distance_km} км")
        if self.weekly_duration_h is not None:
            lines.append(f"- **Время тренировок за 7 дней:** {self.weekly_duration_h} ч")

        acts = self.recent_activities_db or self.recent_activities
        if acts:
            lines.append("\n### Последние тренировки\n")
            for act in acts[:7]:
                if "activityType" in act:
                    sport = act.get("activityType", {}).get("typeKey", "other")
                    dt = act.get("startTimeLocal", "")[:10]
                    dist = act.get("distance", 0) or 0
                    dur = act.get("duration", 0) or 0
                    avg_hr = act.get("averageHR", "—")
                    lines.append(
                        f"- {dt} | {sport} | {dist/1000:.1f} км | "
                        f"{int(dur//60)} мин | ЧСС avg {avg_hr}"
                    )
                else:
                    sport = act.get("sport", "other")
                    dt = act.get("date", "")
                    dur = f"{act['duration_min']} мин" if act.get("duration_min") else ""
                    dist = f"{act['distance_km']} км" if act.get("distance_km") else ""
                    hr = f"ЧСС {act['avg_hr']}" if act.get("avg_hr") else ""
                    strain = f"strain {act['whoop_strain']:.1f}" if act.get("whoop_strain") else ""
                    details = "  ".join(filter(None, [dur, dist, hr, strain]))
                    lines.append(f"- {dt} | {sport} | {details}")

        return "\n".join(lines)


_NO_KEY_MSG = (
    "🔑 AI-функции недоступны: OPENAI_API_KEY не настроен.\n"
    "Добавь ключ в .env и перезапусти бота."
)


class TrainingPlanner:
    """Generates training plans via the injected AIProvider."""

    def __init__(self, provider: Optional[AIProvider] = None) -> None:
        self._provider = provider  # None means «not configured yet»

    def _get_provider(self) -> Optional[AIProvider]:
        if self._provider is not None:
            return self._provider
        try:
            from ai import get_provider
            p = get_provider()
            self._provider = p
            return p
        except RuntimeError:
            return None

    async def generate_weekly_plan(
        self, sport: str, context: AthleteContext, goal: str = ""
    ) -> str:
        provider = self._get_provider()
        if not provider:
            return _NO_KEY_MSG

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
        return await provider.complete(
            system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=2048
        )

    async def generate_single_session(
        self, sport: str, context: AthleteContext, session_type: str = "auto"
    ) -> str:
        provider = self._get_provider()
        if not provider:
            return _NO_KEY_MSG

        sport_label = _SPORT_LABELS.get(sport, sport)

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
        return await provider.complete(
            system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=1024
        )

    async def analyze_recovery(self, context: AthleteContext) -> str:
        provider = self._get_provider()
        if not provider:
            return _NO_KEY_MSG

        user_prompt = f"""\
{context.to_prompt_text()}

Проведи **анализ восстановления** спортсмена:
1. Оцени текущее состояние по шкале (отличное / хорошее / удовлетворительное / низкое).
2. Определи ключевые факторы, влияющие на восстановление.
3. Дай **3–5 конкретных рекомендаций** по улучшению.
4. Укажи, **какие виды тренировок** сегодня оптимальны, а каких следует избегать.\
"""
        return await provider.complete(
            system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=800
        )

    async def answer_question(self, question: str, context: AthleteContext) -> str:
        provider = self._get_provider()
        if not provider:
            return _NO_KEY_MSG

        user_prompt = f"""\
{context.to_prompt_text()}

**Вопрос спортсмена:** {question}\
"""
        return await provider.complete(
            system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=800
        )

    async def generate_daily_recommendation(
        self, context: AthleteContext
    ) -> DailyRecommendation:
        """
        Generate today's structured recommendation.

        Returns a validated DailyRecommendation.
        Raises RuntimeError if provider is not configured.
        Raises ValueError if AI returns invalid JSON or schema mismatch.
        """
        provider = self._get_provider()
        if not provider:
            raise RuntimeError(_NO_KEY_MSG)

        system = """\
Ты — элитный тренер по выносливости. Анализируй данные спортсмена и возвращай \
рекомендацию СТРОГО в виде JSON-объекта без markdown-обёртки и без пояснений вне JSON.

ПРАВИЛА ПРИНЯТИЯ РЕШЕНИЙ:
1. ОТДЫХ обязателен если: WHOOP Recovery < 33% ИЛИ Garmin Body Battery < 25 ИЛИ \
   недосып за 7 дней > 10 ч ИЛИ Garmin Training Readiness < 30.
2. ЛЁГКАЯ тренировка если: Recovery 33–55% ИЛИ Body Battery 25–45 ИЛИ тренд \
   восстановления "declining".
3. Если за последние 4 дня было 3+ тренировки — рекомендуй восстановительную или кросс-тренинг.
4. Учитывай ЦЕЛЬ спортсмена: бегуну на 10К нужны темповые и интервальные работы; \
   марафонцу — длинные Z2 забеги; общий фитнес — разнообразие.
5. Учитывай ДЕНЬ НЕДЕЛИ: варьируй нагрузку по дням (не одно и то же каждый день). \
   В дни силовых — рекомендуй силовую; в выходные — длинную тренировку.
6. HR ЗОНЫ: если в данных есть пульсовые зоны спортсмена, используй ТОЛЬКО ИХ \
   конкретные диапазоны в target_hr_range. Никогда не выдумывай пульсовые значения.
7. В reasoning ссылайся на КОНКРЕТНЫЕ ЦИФРЫ из данных (например: "HRV 48 мс — \
   на 5 мс выше среднего за 7 дней", "3 беговые за 4 дня — нужен отдых").
8. readiness_score должен коррелировать с Recovery и Training Readiness \
   (Recovery 80+ → readiness 70+; Recovery < 33% → readiness < 40).
9. confidence: "high" если есть WHOOP + Garmin + профиль; "medium" если один источник \
   отсутствует; "low" если данных минимально.
10. data_gaps: перечисли конкретно что отсутствует (Garmin Training Readiness, \
    профиль спортсмена, HR зоны и т.д.).

Схема JSON:
{
  "readiness_score": <0-100>,
  "status_label": "<краткий статус, например: Умеренная готовность>",
  "main_recommendation": "<главная рекомендация одной фразой>",
  "planned_workout": {
    "sport": "<run|bike|swim|strength|walk|mobility|recovery|rest|other>",
    "title": "<название тренировки>",
    "duration_minutes": <число или null>,
    "intensity": "<z1|z2|z3|z4|z5|easy|moderate|hard|rest>",
    "blocks": [
      {
        "title": "<название блока>",
        "duration_minutes": <число>,
        "target_hr_zone": "<z1-z5 или null>",
        "target_hr_range": "<например 130-145 или null>",
        "notes": "<заметки или null>"
      }
    ]
  },
  "reasoning": ["<факт 1 с конкретными цифрами>", "<факт 2>"],
  "avoid": ["<чего избегать 1>"],
  "control": ["<сигнал для остановки 1>"],
  "confidence": "<low|medium|high>",
  "data_gaps": ["<чего не хватает для полного анализа>"]
}\
"""

        user_prompt = context.to_prompt_text()

        raw = await provider.complete(system=system, user=user_prompt, max_tokens=1024)

        # Strip accidental markdown fences
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("AI returned invalid JSON: %s\nRaw: %.500s", exc, raw)
            raise ValueError(f"AI вернул невалидный JSON: {exc}") from exc

        try:
            return DailyRecommendation.model_validate(data)
        except ValidationError as exc:
            logger.error("AI JSON failed schema validation: %s\nData: %s", exc, data)
            raise ValueError(f"AI JSON не прошёл валидацию схемы: {exc}") from exc


# Module-level singleton
planner = TrainingPlanner()
