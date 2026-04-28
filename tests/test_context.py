"""Tests for bot/handlers/today.py:_build_context — context building from snapshots and activities."""

from __future__ import annotations

import pytest
from datetime import date, timedelta
from tests.conftest import MockSnapshot, MockActivity, MockProfile


# Import _build_context directly
from bot.handlers.today import _build_context


class TestBuildContextEmpty:
    def test_empty_snapshots_and_activities(self):
        ctx = _build_context([], [], None)
        assert ctx.whoop_recovery_score is None
        assert ctx.completed_today is None
        assert ctx.weekly_load_by_sport is None

    def test_empty_snapshots_with_activities(self):
        today = date.today().isoformat()
        activities = [
            MockActivity(sport="run", activity_date=today,
                         duration_s=2700.0, external_id="1"),
        ]
        ctx = _build_context([], activities, None)
        assert ctx.whoop_recovery_score is None
        assert "run" in ctx.completed_today


class TestBuildContextWhoop:
    def test_single_snapshot(self):
        snap = MockSnapshot(
            whoop_recovery_score=72.0,
            whoop_hrv_ms=48.5,
            whoop_resting_hr=52.0,
            whoop_strain=10.5,
            whoop_sleep_performance=85.0,
            whoop_spo2=97.0,
            whoop_skin_temp=33.2,
            whoop_respiratory_rate=15.2,
            whoop_sleep_duration_h=7.8,
        )
        ctx = _build_context([snap], [], None)

        assert ctx.whoop_recovery_score == 72.0
        assert ctx.whoop_hrv_ms == 48.5
        assert ctx.whoop_resting_hr == 52.0
        assert ctx.whoop_strain_today == 10.5
        assert ctx.whoop_sleep_performance == 85.0

    def test_garmin_fallback_to_older_snapshot(self):
        today = MockSnapshot(garmin_training_readiness=None, garmin_body_battery_end=None)
        yesterday = MockSnapshot(garmin_training_readiness=75, garmin_body_battery_end=80)

        ctx = _build_context([today, yesterday], [], None)
        assert ctx.garmin_training_readiness == 75
        assert ctx.garmin_body_battery == 80


class TestBuildContextTrends:
    def test_7day_averages(self, make_snapshots):
        snapshots = make_snapshots(n=7, hrv_base=40.0, sleep_perf_base=80.0)
        ctx = _build_context(snapshots, [], None)

        assert ctx.hrv_7d_avg is not None
        assert ctx.sleep_7d_avg is not None

    def test_recovery_trend_improving(self):
        """Recent 3 days higher recovery than older 4 → improving."""
        snapshots = []
        # Recent 3: recovery 80
        for _ in range(3):
            snapshots.append(MockSnapshot(whoop_recovery_score=80.0, whoop_hrv_ms=50.0))
        # Older 4: recovery 60
        for _ in range(4):
            snapshots.append(MockSnapshot(whoop_recovery_score=60.0, whoop_hrv_ms=40.0))

        ctx = _build_context(snapshots, [], None)
        assert ctx.recovery_trend == "improving"

    def test_recovery_trend_declining(self):
        """Recent 3 days lower recovery than older 4 → declining."""
        snapshots = []
        for _ in range(3):
            snapshots.append(MockSnapshot(whoop_recovery_score=40.0, whoop_hrv_ms=35.0))
        for _ in range(4):
            snapshots.append(MockSnapshot(whoop_recovery_score=70.0, whoop_hrv_ms=50.0))

        ctx = _build_context(snapshots, [], None)
        assert ctx.recovery_trend == "declining"

    def test_recovery_trend_stable(self):
        """Similar recovery → stable."""
        snapshots = [MockSnapshot(whoop_recovery_score=65.0, whoop_hrv_ms=45.0) for _ in range(7)]
        ctx = _build_context(snapshots, [], None)
        assert ctx.recovery_trend == "stable"

    def test_strain_averages(self):
        snapshots = [MockSnapshot(whoop_strain=10.0 + i) for i in range(7)]
        ctx = _build_context(snapshots, [], None)

        assert ctx.strain_7d_avg is not None
        assert ctx.weekly_strain_total is not None
        assert ctx.weekly_strain_total > ctx.strain_7d_avg

    def test_sleep_debt(self):
        # 7 days sleeping 7h = 7h deficit
        snapshots = [MockSnapshot(whoop_sleep_duration_h=7.0) for _ in range(7)]
        ctx = _build_context(snapshots, [], None)
        assert ctx.sleep_debt_h == -7.0  # 7 * (7 - 8) = -7

    def test_sleep_surplus(self):
        snapshots = [MockSnapshot(whoop_sleep_duration_h=9.0) for _ in range(7)]
        ctx = _build_context(snapshots, [], None)
        assert ctx.sleep_debt_h == 7.0  # 7 * (9 - 8) = 7

    def test_not_enough_snapshots_no_trends(self):
        snapshots = [MockSnapshot(whoop_recovery_score=70.0)]
        ctx = _build_context(snapshots, [], None)
        assert ctx.recovery_trend is None
        assert ctx.strain_7d_avg is None


class TestBuildContextActivities:
    def test_weekly_load_aggregation(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        activities = [
            MockActivity(sport="run", activity_date=today,
                         duration_s=2700.0, distance_m=8000.0, external_id="1"),
            MockActivity(sport="run", activity_date=yesterday,
                         duration_s=3600.0, distance_m=12000.0, external_id="2"),
            MockActivity(sport="strength", activity_date=today,
                         duration_s=3600.0, external_id="3"),
        ]

        ctx = _build_context([], activities, None)
        assert "run" in ctx.weekly_load_by_sport
        assert ctx.weekly_load_by_sport["run"]["count"] == 2
        assert ctx.weekly_load_by_sport["run"]["duration_min"] == 105  # 45 + 60
        assert ctx.weekly_load_by_sport["strength"]["count"] == 1

    def test_completed_today(self):
        today = date.today().isoformat()
        activities = [
            MockActivity(sport="run", activity_date=today, external_id="1"),
            MockActivity(sport="strength", activity_date=today, external_id="2"),
        ]
        ctx = _build_context([], activities, None)
        assert set(ctx.completed_today) == {"run", "strength"}

    def test_old_activities_not_in_completed_today(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        activities = [
            MockActivity(sport="run", activity_date=yesterday, external_id="1"),
        ]
        ctx = _build_context([], activities, None)
        assert ctx.completed_today == []

    def test_recent_activities_limited_to_10(self):
        today = date.today().isoformat()
        activities = [
            MockActivity(sport="run", activity_date=today,
                         duration_s=1800.0, external_id=str(i))
            for i in range(15)
        ]
        ctx = _build_context([], activities, None)
        assert len(ctx.recent_activities_db) == 10

    def test_dedup_garmin_whoop(self):
        """Same workout from both sources → merged, counted once."""
        today = date.today().isoformat()
        activities = [
            MockActivity(source="garmin", sport="run", activity_date=today,
                         duration_s=2700.0, distance_m=8000.0, external_id="g1"),
            MockActivity(source="whoop", sport="run", activity_date=today,
                         duration_s=2680.0, whoop_strain=12.0, external_id="w1"),
        ]
        ctx = _build_context([], activities, None)
        assert ctx.weekly_load_by_sport["run"]["count"] == 1


class TestBuildContextHrZones:
    def test_hr_zones_from_profile(self):
        ctx = _build_context([], [], MockProfile(max_hr=190))
        assert ctx.hr_zones is not None

    def test_no_hr_zones_without_profile(self):
        ctx = _build_context([], [], None)
        assert ctx.hr_zones is None

    def test_no_hr_zones_without_max_hr(self):
        ctx = _build_context([], [], MockProfile(max_hr=None))
        assert ctx.hr_zones is None
