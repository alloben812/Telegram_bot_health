"""Tests for training/planner.py — AthleteContext and AI recommendation."""

from __future__ import annotations

import json
import pytest
from training.planner import AthleteContext, TrainingPlanner


class TestAthleteContextPrompt:
    def test_full_whoop_data(self):
        ctx = AthleteContext(
            whoop_recovery_score=72.0,
            whoop_hrv_ms=48.5,
            whoop_resting_hr=52.0,
            whoop_strain_today=10.5,
            whoop_sleep_performance=85.0,
            whoop_spo2=97.0,
            whoop_skin_temp=33.2,
            whoop_respiratory_rate=15.2,
            whoop_sleep_duration_h=7.8,
            hrv_7d_avg=45.0,
            sleep_7d_avg=82.0,
        )
        text = ctx.to_prompt_text()

        assert "72.0%" in text  # recovery
        assert "48.5 мс" in text  # HRV
        assert "52.0 уд/мин" in text  # resting HR
        assert "10.5" in text  # strain
        assert "85.0%" in text  # sleep perf
        assert "97.0%" in text  # SpO2
        assert "7.8 ч" in text  # sleep duration

    def test_whoop_only_no_garmin(self):
        ctx = AthleteContext(
            whoop_recovery_score=72.0,
            whoop_hrv_ms=48.5,
        )
        text = ctx.to_prompt_text()

        assert "WHOOP" in text or "Восстановление" in text
        assert "Garmin" not in text  # no garmin data shown

    def test_garmin_data_shown(self):
        ctx = AthleteContext(
            garmin_training_readiness=75,
            garmin_body_battery=80,
            garmin_steps_today=8000,
            garmin_stress_avg=35,
            garmin_active_calories=450,
        )
        text = ctx.to_prompt_text()

        assert "75/100" in text
        assert "Body Battery" in text
        assert "8,000" in text  # steps formatted

    def test_trends_section(self):
        ctx = AthleteContext(
            recovery_trend="improving",
            strain_7d_avg=12.5,
            weekly_strain_total=87.5,
            sleep_debt_h=-3.5,
        )
        text = ctx.to_prompt_text()

        assert "улучшается" in text
        assert "↗" in text
        assert "12.5" in text
        assert "87.5" in text
        assert "3.5 ч" in text  # sleep debt

    def test_trends_declining(self):
        ctx = AthleteContext(recovery_trend="declining")
        text = ctx.to_prompt_text()
        assert "↘" in text
        assert "снижается" in text

    def test_trends_stable(self):
        ctx = AthleteContext(recovery_trend="stable")
        text = ctx.to_prompt_text()
        assert "→" in text

    def test_sleep_surplus(self):
        ctx = AthleteContext(sleep_debt_h=2.0)
        text = ctx.to_prompt_text()
        assert "Избыток сна" in text

    def test_completed_today(self):
        ctx = AthleteContext(completed_today=["run", "strength"])
        text = ctx.to_prompt_text()
        assert "run" in text
        assert "strength" in text

    def test_weekly_load_detail(self):
        ctx = AthleteContext(
            weekly_load_detail=[
                "- 🏃 run: 3 тр.  120 мин  25.5 км",
                "- 💪 strength: 2 тр.  90 мин",
            ]
        )
        text = ctx.to_prompt_text()
        assert "Нагрузка за 7 дней" in text
        assert "25.5 км" in text

    def test_recent_activities(self):
        ctx = AthleteContext(
            recent_activities_db=[
                {"sport": "run", "date": "2024-01-15",
                 "duration_min": 45, "distance_km": 8.5,
                 "avg_hr": 155, "whoop_strain": 12.3},
            ]
        )
        text = ctx.to_prompt_text()
        assert "2024-01-15" in text
        assert "run" in text

    def test_empty_context(self):
        ctx = AthleteContext()
        text = ctx.to_prompt_text()
        assert "Данные спортсмена" in text


class TestGenerateDailyRecommendation:
    async def test_valid_json_response(self, mock_ai_provider):
        planner = TrainingPlanner(provider=mock_ai_provider)
        ctx = AthleteContext(whoop_recovery_score=72.0)

        rec = await planner.generate_daily_recommendation(ctx)

        assert rec.readiness_score == 72
        assert rec.planned_workout.sport == "run"
        assert rec.confidence == "medium"
        assert len(mock_ai_provider.calls) == 1

    async def test_invalid_json_raises(self, mock_ai_provider):
        mock_ai_provider.response = "not valid json at all"
        planner = TrainingPlanner(provider=mock_ai_provider)
        ctx = AthleteContext()

        with pytest.raises(ValueError, match="невалидный JSON"):
            await planner.generate_daily_recommendation(ctx)

    async def test_markdown_fence_stripped(self, mock_ai_provider):
        from tests.conftest import VALID_RECOMMENDATION_JSON
        mock_ai_provider.response = f"```json\n{VALID_RECOMMENDATION_JSON}\n```"
        planner = TrainingPlanner(provider=mock_ai_provider)
        ctx = AthleteContext()

        rec = await planner.generate_daily_recommendation(ctx)
        assert rec.readiness_score == 72

    async def test_no_provider_raises(self):
        planner = TrainingPlanner(provider=None)
        # Prevent fallback to real provider
        planner._get_provider = lambda: None
        ctx = AthleteContext()

        with pytest.raises(RuntimeError):
            await planner.generate_daily_recommendation(ctx)
