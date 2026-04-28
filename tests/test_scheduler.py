"""Tests for bot/scheduler.py — sync jobs and notifications."""

from __future__ import annotations

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


class TestDoSync:
    """Test _do_sync return values with full mock."""

    async def test_whoop_ok_garmin_error(self):
        with patch("bot.scheduler._do_sync") as mock_sync:
            mock_sync.return_value = (True, ["Garmin: 429 Too Many Requests"])
            saved, errors = await mock_sync(12345)
            assert saved is True
            assert len(errors) == 1
            assert "Garmin" in errors[0]

    async def test_both_fail(self):
        with patch("bot.scheduler._do_sync") as mock_sync:
            mock_sync.return_value = (False, ["Garmin: error", "WHOOP: error"])
            saved, errors = await mock_sync(12345)
            assert saved is False
            assert len(errors) == 2


class TestSilentSyncNotification:
    """Test that job_silent_sync sends notifications for new workouts."""

    async def test_new_workout_sends_notification(self, patch_db):
        from database.db import get_or_create_user

        await get_or_create_user(12345)

        mock_bot = AsyncMock()
        mock_context = MagicMock()
        mock_context.bot = mock_bot

        with patch("bot.scheduler._do_sync", new_callable=AsyncMock) as mock_sync, \
             patch("bot.scheduler.config") as mock_config, \
             patch("database.db.get_activities_for_date", new_callable=AsyncMock) as mock_gaf, \
             patch("database.db.get_planned_workout", new_callable=AsyncMock) as mock_pw:

            mock_config.ADMIN_TELEGRAM_ID = 12345
            mock_sync.return_value = (True, [])
            mock_pw.return_value = None

            detected = MagicMock(
                external_id="5001", sport="run", duration_s=2700.0,
                whoop_strain=12.3, source="whoop",
            )
            mock_gaf.side_effect = [[], [detected]]  # before=empty, after=1 activity

            from bot.scheduler import job_silent_sync
            await job_silent_sync(mock_context)

            mock_bot.send_message.assert_called_once()
            msg_text = mock_bot.send_message.call_args.kwargs.get("text", "")
            assert "Обнаружена тренировка" in msg_text


class TestSilentSyncAutoComplete:
    """Test auto-completion of planned workout when matching activity detected."""

    async def test_matching_sport_auto_completes(self, patch_db):
        from database.db import (
            get_or_create_user, save_daily_recommendation, get_planned_workout,
        )
        from ai.schemas import DailyRecommendation, PlannedWorkout, WorkoutBlock

        await get_or_create_user(12345)
        today = date.today().isoformat()

        rec = DailyRecommendation(
            readiness_score=70, status_label="OK", main_recommendation="Run",
            planned_workout=PlannedWorkout(
                sport="run", title="Easy run", duration_minutes=45,
                intensity="z2", blocks=[WorkoutBlock(title="Main", duration_minutes=45)],
            ),
            reasoning=["HRV ok"], avoid=["Intervals"], control=["HR < 160"],
            confidence="medium", data_gaps=[],
        )
        _, workout_record = await save_daily_recommendation(
            user_id=12345, date=today, rec=rec,
        )
        assert workout_record.status == "proposed"

        mock_bot = AsyncMock()
        mock_context = MagicMock()
        mock_context.bot = mock_bot

        with patch("bot.scheduler._do_sync", new_callable=AsyncMock) as mock_sync, \
             patch("bot.scheduler.config") as mock_config, \
             patch("database.db.get_activities_for_date", new_callable=AsyncMock) as mock_gaf:

            mock_config.ADMIN_TELEGRAM_ID = 12345
            mock_sync.return_value = (True, [])

            detected = MagicMock(
                external_id="w5001", sport="run", duration_s=2700.0,
                whoop_strain=12.3, source="whoop",
            )
            mock_gaf.side_effect = [[], [detected]]

            from bot.scheduler import job_silent_sync
            await job_silent_sync(mock_context)

            mock_bot.send_message.assert_called_once()
            msg_text = mock_bot.send_message.call_args.kwargs.get("text", "")
            assert "выполнена" in msg_text

            updated = await get_planned_workout(12345, today)
            assert updated.status == "completed"
