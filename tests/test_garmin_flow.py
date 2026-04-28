"""Tests for Garmin data pipeline — fetch → extract → store → context → prompt."""

from __future__ import annotations

import pytest
from datetime import date
from tests.conftest import MockSnapshot, MockProfile

from bot.handlers.today import _build_context
from training.planner import AthleteContext


# ── Mock Garmin API responses ───────────────────────────────────────

MOCK_TRAINING_READINESS = {
    "userProfilePK": 12345,
    "calendarDate": "2026-04-28",
    "score": 78,
    "level": "MODERATE",
    "sleepScore": 65,
    "recoveryScore": 72,
    "activityHistoryScore": 80,
}

MOCK_BODY_BATTERY = [
    {"startTimestampGMT": "2026-04-28T00:00:00", "bodyBatteryLevel": 95, "charged": 95},
    {"startTimestampGMT": "2026-04-28T06:00:00", "bodyBatteryLevel": 88, "charged": 0},
    {"startTimestampGMT": "2026-04-28T12:00:00", "bodyBatteryLevel": 45, "charged": 0},
    {"startTimestampGMT": "2026-04-28T18:00:00", "bodyBatteryLevel": 22, "charged": 0},
]


class TestGarminDataExtraction:
    """Test that upsert_daily_snapshot correctly extracts Garmin fields."""

    async def test_training_readiness_extracted(self, patch_db):
        from database.db import upsert_daily_snapshot, get_recent_snapshots, get_or_create_user

        await get_or_create_user(12345)
        today = date.today().isoformat()

        garmin_data = {
            "totalSteps": 8500,
            "activeKilocalories": 450,
            "averageStressLevel": 35,
            "_training_readiness": MOCK_TRAINING_READINESS,
            "_body_battery": MOCK_BODY_BATTERY,
        }

        await upsert_daily_snapshot(12345, today, garmin_data=garmin_data)

        snaps = await get_recent_snapshots(12345, days=1)
        assert len(snaps) == 1
        assert snaps[0].garmin_training_readiness == 78
        assert snaps[0].garmin_body_battery_end == 22  # last entry
        assert snaps[0].garmin_steps == 8500

    async def test_missing_training_readiness(self, patch_db):
        from database.db import upsert_daily_snapshot, get_recent_snapshots, get_or_create_user

        await get_or_create_user(12345)
        today = date.today().isoformat()

        garmin_data = {
            "totalSteps": 5000,
            # No _training_readiness or _body_battery
        }

        await upsert_daily_snapshot(12345, today, garmin_data=garmin_data)

        snaps = await get_recent_snapshots(12345, days=1)
        assert snaps[0].garmin_training_readiness is None
        assert snaps[0].garmin_body_battery_end is None

    async def test_empty_body_battery_list(self, patch_db):
        from database.db import upsert_daily_snapshot, get_recent_snapshots, get_or_create_user

        await get_or_create_user(12345)
        today = date.today().isoformat()

        garmin_data = {
            "totalSteps": 3000,
            "_body_battery": [],
        }

        await upsert_daily_snapshot(12345, today, garmin_data=garmin_data)

        snaps = await get_recent_snapshots(12345, days=1)
        assert snaps[0].garmin_body_battery_end is None


class TestGarminInContext:
    """Test that Garmin data flows through _build_context into AthleteContext."""

    def test_training_readiness_in_context(self):
        snap = MockSnapshot(
            garmin_training_readiness=78,
            garmin_body_battery_end=45,
            garmin_steps=8500,
            garmin_stress_avg=35,
        )
        ctx = _build_context([snap], [], None)
        assert ctx.garmin_training_readiness == 78
        assert ctx.garmin_body_battery == 45
        assert ctx.garmin_steps_today == 8500
        assert ctx.garmin_stress_avg == 35

    def test_garmin_fallback_across_snapshots(self):
        """Today's snapshot has no Garmin data, yesterday's does."""
        today = MockSnapshot()
        yesterday = MockSnapshot(
            garmin_training_readiness=72,
            garmin_body_battery_end=60,
        )
        ctx = _build_context([today, yesterday], [], None)
        assert ctx.garmin_training_readiness == 72
        assert ctx.garmin_body_battery == 60


class TestGarminInPrompt:
    """Test that Garmin fields appear in AI prompt text."""

    def test_training_readiness_in_prompt(self):
        ctx = AthleteContext(
            garmin_training_readiness=78,
            garmin_body_battery=45,
            garmin_steps_today=8500,
        )
        text = ctx.to_prompt_text()
        assert "Готовность (Garmin)" in text
        assert "78/100" in text
        assert "Body Battery" in text
        assert "45/100" in text
        assert "8,500" in text

    def test_no_garmin_no_garmin_section(self):
        ctx = AthleteContext(whoop_recovery_score=72.0)
        text = ctx.to_prompt_text()
        assert "Garmin" not in text


class TestFullGarminPipeline:
    """End-to-end: mock Garmin data → snapshot → context → prompt."""

    async def test_full_pipeline(self, patch_db):
        from database.db import (
            get_or_create_user, upsert_daily_snapshot, get_recent_snapshots,
        )

        await get_or_create_user(12345)
        today = date.today().isoformat()

        # Simulate what _do_sync produces
        garmin_data = {
            "totalSteps": 10000,
            "activeKilocalories": 500,
            "averageStressLevel": 30,
            "_training_readiness": {"score": 85},
            "_body_battery": [
                {"bodyBatteryLevel": 90},
                {"bodyBatteryLevel": 55},
            ],
        }
        whoop_data = {
            "recovery": {"score": {"recovery_score": 80, "hrv_rmssd_milli": 50.0, "resting_heart_rate": 55}},
            "sleep": {"score": {"sleep_performance_percentage": 88}},
            "cycle": {},
        }

        await upsert_daily_snapshot(12345, today, garmin_data=garmin_data, whoop_data=whoop_data)

        snaps = await get_recent_snapshots(12345, days=1)
        profile = MockProfile(max_hr=190, active_goal_key="run_10k_60")
        ctx = _build_context(snaps, [], profile)

        # Verify all data reaches context
        assert ctx.whoop_recovery_score == 80
        assert ctx.whoop_hrv_ms == 50.0
        assert ctx.garmin_training_readiness == 85
        assert ctx.garmin_body_battery == 55  # last entry
        assert ctx.garmin_steps_today == 10000
        assert ctx.goal_label == "10 км за 60 минут"

        # Verify prompt text contains all sections
        text = ctx.to_prompt_text()
        assert "Профиль спортсмена" in text
        assert "10 км за 60 минут" in text
        assert "Данные спортсмена" in text
        assert "80.0%" in text  # WHOOP recovery
        assert "85/100" in text  # Garmin training readiness
        assert "55/100" in text  # Body battery
