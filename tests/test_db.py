"""Tests for database/db.py — CRUD operations with in-memory SQLite."""

from __future__ import annotations

import pytest
from datetime import date, timedelta


class TestInitDb:
    async def test_tables_created(self, patch_db):
        from database.db import init_db
        await init_db()


class TestUserCrud:
    async def test_create_and_get_user(self, patch_db):
        from database.db import get_or_create_user, get_user

        await get_or_create_user(12345, username="testuser", first_name="Test")
        user = await get_user(12345)
        assert user is not None
        assert user.id == 12345
        assert user.username == "testuser"

    async def test_get_nonexistent_user(self, patch_db):
        from database.db import get_user
        assert await get_user(99999) is None

    async def test_idempotent(self, patch_db):
        from database.db import get_or_create_user, get_user

        await get_or_create_user(12345, username="v1")
        await get_or_create_user(12345, username="v2")
        user = await get_user(12345)
        assert user is not None


class TestSaveWhoopWorkouts:
    async def test_insert_new_workout(self, patch_db):
        from database.db import save_whoop_workouts, get_activities_for_date

        today = date.today().isoformat()
        workouts = [{
            "id": 99001,
            "sport_id": 0,
            "sport_name": "Running",
            "start": f"{today}T08:00:00.000Z",
            "end": f"{today}T08:45:00.000Z",
            "score": {
                "strain": 12.3,
                "average_heart_rate": 155,
                "max_heart_rate": 178,
                "kilojoule": 1800.0,
                "distance_meter": 8500.0,
            },
        }]
        count = await save_whoop_workouts(12345, workouts)
        assert count == 1

        activities = await get_activities_for_date(12345, today)
        assert len(activities) == 1
        assert activities[0].source == "whoop"
        assert activities[0].sport == "run"  # normalized from "Running"
        assert activities[0].whoop_strain == 12.3

    async def test_dedup_by_external_id(self, patch_db):
        from database.db import save_whoop_workouts

        today = date.today().isoformat()
        workout = [{
            "id": 99001, "sport_name": "Running",
            "start": f"{today}T08:00:00.000Z",
            "end": f"{today}T08:45:00.000Z", "score": {},
        }]
        assert await save_whoop_workouts(12345, workout) == 1
        assert await save_whoop_workouts(12345, workout) == 0  # duplicate

    async def test_empty_list(self, patch_db):
        from database.db import save_whoop_workouts
        assert await save_whoop_workouts(12345, []) == 0


class TestSaveGarminActivities:
    async def test_insert_and_normalize(self, patch_db):
        from database.db import save_garmin_activities, get_activities_for_date

        today = date.today().isoformat()
        activities = [{
            "activityId": 88001,
            "activityType": {"typeKey": "running"},
            "startTimeLocal": f"{today} 08:02:00",
            "duration": 2680.0,
            "distance": 8450.0,
            "averageHR": 153,
            "maxHR": 176,
            "calories": 430,
        }]
        count = await save_garmin_activities(12345, activities)
        assert count == 1

        result = await get_activities_for_date(12345, today)
        assert len(result) == 1
        assert result[0].sport == "run"  # normalized from "running"
        assert result[0].source == "garmin"

    async def test_dedup_by_external_id(self, patch_db):
        from database.db import save_garmin_activities

        today = date.today().isoformat()
        activity = [{
            "activityId": 88001,
            "activityType": {"typeKey": "running"},
            "startTimeLocal": f"{today} 08:02:00",
            "duration": 2680.0,
        }]
        assert await save_garmin_activities(12345, activity) == 1
        assert await save_garmin_activities(12345, activity) == 0


class TestGetActivities:
    async def test_get_activities_for_date(self, patch_db):
        from database.db import save_whoop_workouts, get_activities_for_date

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        workouts = [
            {
                "id": 1001, "sport_name": "Running",
                "start": f"{today}T08:00:00.000Z",
                "end": f"{today}T08:45:00.000Z", "score": {},
            },
            {
                "id": 1002, "sport_name": "Cycling",
                "start": f"{yesterday}T08:00:00.000Z",
                "end": f"{yesterday}T09:00:00.000Z", "score": {},
            },
        ]
        await save_whoop_workouts(12345, workouts)

        today_acts = await get_activities_for_date(12345, today)
        assert len(today_acts) == 1
        assert today_acts[0].sport == "run"

        yest_acts = await get_activities_for_date(12345, yesterday)
        assert len(yest_acts) == 1
        assert yest_acts[0].sport == "bike"

    async def test_get_recent_activities_days_filter(self, patch_db):
        from database.db import save_whoop_workouts, get_recent_activities

        today = date.today().isoformat()
        workouts = [{
            "id": 2001, "sport_name": "Running",
            "start": f"{today}T08:00:00.000Z",
            "end": f"{today}T08:45:00.000Z", "score": {},
        }]
        await save_whoop_workouts(12345, workouts)

        result = await get_recent_activities(12345, days=1)
        assert len(result) == 1


class TestDailySnapshot:
    async def test_upsert_create(self, patch_db):
        from database.db import upsert_daily_snapshot, get_recent_snapshots

        today = date.today().isoformat()
        whoop_data = {
            "recovery": {
                "score": {"recovery_score": 72, "hrv_rmssd_milli": 48.5, "resting_heart_rate": 52},
            },
            "sleep": {"score": {"sleep_performance_percentage": 85}},
            "cycle": {"score": {"strain": 10.5}},
        }
        await upsert_daily_snapshot(12345, today, whoop_data=whoop_data)

        snaps = await get_recent_snapshots(12345, days=1)
        assert len(snaps) == 1
        assert snaps[0].whoop_recovery_score == 72
        assert snaps[0].whoop_hrv_ms == 48.5

    async def test_upsert_update(self, patch_db):
        from database.db import upsert_daily_snapshot, get_recent_snapshots

        today = date.today().isoformat()
        await upsert_daily_snapshot(12345, today, whoop_data={
            "recovery": {"score": {"recovery_score": 50}},
        })
        await upsert_daily_snapshot(12345, today, whoop_data={
            "recovery": {"score": {"recovery_score": 72}},
        })

        snaps = await get_recent_snapshots(12345, days=1)
        assert len(snaps) == 1
        assert snaps[0].whoop_recovery_score == 72


class TestWorkoutCompletion:
    async def test_save_completion_updates_planned_status(self, patch_db):
        from database.db import save_daily_recommendation, save_workout_completion, get_planned_workout
        from ai.schemas import DailyRecommendation, PlannedWorkout, WorkoutBlock

        rec = DailyRecommendation(
            readiness_score=70,
            status_label="OK",
            main_recommendation="Test",
            planned_workout=PlannedWorkout(
                sport="run", title="Test run", duration_minutes=30,
                intensity="z2", blocks=[WorkoutBlock(title="Main", duration_minutes=30)],
            ),
            reasoning=["HRV в норме"],
            avoid=["Интервалы"],
            control=["ЧСС < 160"],
            confidence="medium",
            data_gaps=[],
        )

        rec_record, workout_record = await save_daily_recommendation(
            user_id=12345, date="2024-01-15", rec=rec,
        )
        assert workout_record.status == "proposed"

        await save_workout_completion(
            planned_workout_id=workout_record.id,
            user_id=12345,
            completion_status="done",
        )

        updated = await get_planned_workout(12345, "2024-01-15")
        assert updated.status == "completed"

    async def test_auto_detected_completion(self, patch_db):
        from database.db import save_daily_recommendation, save_workout_completion, get_planned_workout
        from ai.schemas import DailyRecommendation, PlannedWorkout, WorkoutBlock

        rec = DailyRecommendation(
            readiness_score=70, status_label="OK", main_recommendation="Test",
            planned_workout=PlannedWorkout(
                sport="run", title="Test", duration_minutes=30,
                intensity="z2", blocks=[WorkoutBlock(title="M", duration_minutes=30)],
            ),
            reasoning=["test"], avoid=["none"], control=["hr"],
            confidence="medium", data_gaps=[],
        )

        _, workout = await save_daily_recommendation(user_id=12345, date="2024-01-15", rec=rec)

        await save_workout_completion(
            planned_workout_id=workout.id,
            user_id=12345,
            completion_status="auto_detected",
        )

        updated = await get_planned_workout(12345, "2024-01-15")
        assert updated.status == "completed"
