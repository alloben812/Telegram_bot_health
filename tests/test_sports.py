"""Tests for training/sports.py — sport normalization and activity deduplication."""

from __future__ import annotations

import pytest
from tests.conftest import MockActivity
from training.sports import CANONICAL_SPORT_MAP, normalize_sport, merge_activities, _MergedActivity


# ── normalize_sport ──────────────────────────────────────────────────


class TestNormalizeSport:
    def test_running_to_run(self):
        assert normalize_sport("running") == "run"

    def test_case_insensitive(self):
        assert normalize_sport("Running") == "run"
        assert normalize_sport("CYCLING") == "bike"

    def test_whitespace_stripped(self):
        assert normalize_sport("  swimming  ") == "swim"

    def test_garmin_trail_running(self):
        assert normalize_sport("trail_running") == "run"

    def test_garmin_strength_training(self):
        assert normalize_sport("strength_training") == "strength"

    def test_whoop_functional_fitness(self):
        assert normalize_sport("functional_fitness") == "strength"

    def test_yoga_to_mobility(self):
        assert normalize_sport("yoga") == "mobility"

    def test_hiit(self):
        assert normalize_sport("hiit") == "hiit"

    def test_walking(self):
        assert normalize_sport("walking") == "walk"

    def test_unknown_passthrough(self):
        assert normalize_sport("unknown_sport_123") == "unknown_sport_123"

    def test_empty_string(self):
        assert normalize_sport("") == "other"

    def test_none(self):
        assert normalize_sport(None) == "other"

    def test_already_canonical(self):
        assert normalize_sport("run") == "run"
        assert normalize_sport("bike") == "bike"
        assert normalize_sport("swim") == "swim"
        assert normalize_sport("strength") == "strength"

    def test_all_map_values_are_short_keys(self):
        """All mapped values should be one of our canonical short keys."""
        valid_keys = {"run", "bike", "swim", "strength", "hiit", "walk",
                      "mobility", "other", "rest"}
        for raw, canonical in CANONICAL_SPORT_MAP.items():
            assert canonical in valid_keys, f"{raw!r} maps to unexpected {canonical!r}"


# ── merge_activities ─────────────────────────────────────────────────


class TestMergeActivities:
    def test_empty_list(self):
        assert merge_activities([]) == []

    def test_single_activity_unchanged(self):
        a = MockActivity(source="whoop", sport="run", activity_date="2024-01-15",
                         duration_s=2700.0, external_id="w1")
        result = merge_activities([a])
        assert len(result) == 1
        assert result[0] is a

    def test_same_workout_garmin_whoop_merged(self):
        """Garmin + WHOOP same date, same sport, similar duration → merged."""
        garmin = MockActivity(
            source="garmin", sport="run", activity_date="2024-01-15",
            duration_s=2700.0, distance_m=8500.0, avg_hr=153,
            avg_pace_s_per_km=318.0, elevation_gain_m=45.0, external_id="g1",
        )
        whoop = MockActivity(
            source="whoop", sport="run", activity_date="2024-01-15",
            duration_s=2680.0, avg_hr=155, whoop_strain=12.3, external_id="w1",
        )
        result = merge_activities([garmin, whoop])
        assert len(result) == 1
        merged = result[0]
        assert isinstance(merged, _MergedActivity)
        assert merged.source == "merged"
        assert merged.avg_pace_s_per_km == 318.0  # from garmin
        assert merged.whoop_strain == 12.3  # from whoop
        assert merged.elevation_gain_m == 45.0  # from garmin
        assert merged.distance_m == 8500.0  # from garmin

    def test_different_sports_not_merged(self):
        """Garmin run + WHOOP strength → 2 separate activities."""
        garmin = MockActivity(
            source="garmin", sport="run", activity_date="2024-01-15",
            duration_s=2700.0, external_id="g1",
        )
        whoop = MockActivity(
            source="whoop", sport="strength", activity_date="2024-01-15",
            duration_s=3600.0, external_id="w1",
        )
        result = merge_activities([garmin, whoop])
        assert len(result) == 2

    def test_very_different_duration_not_merged(self):
        """Same sport but duration differs by >30% → not merged."""
        garmin = MockActivity(
            source="garmin", sport="run", activity_date="2024-01-15",
            duration_s=2700.0, external_id="g1",
        )
        whoop = MockActivity(
            source="whoop", sport="run", activity_date="2024-01-15",
            duration_s=600.0, external_id="w1",  # much shorter
        )
        result = merge_activities([garmin, whoop])
        assert len(result) == 2

    def test_same_source_not_merged(self):
        """Two WHOOP activities with same sport/date → kept separate."""
        w1 = MockActivity(
            source="whoop", sport="run", activity_date="2024-01-15",
            duration_s=2700.0, external_id="w1",
        )
        w2 = MockActivity(
            source="whoop", sport="run", activity_date="2024-01-15",
            duration_s=1800.0, external_id="w2",
        )
        result = merge_activities([w1, w2])
        assert len(result) == 2

    def test_different_dates_not_merged(self):
        garmin = MockActivity(
            source="garmin", sport="run", activity_date="2024-01-15",
            duration_s=2700.0, external_id="g1",
        )
        whoop = MockActivity(
            source="whoop", sport="run", activity_date="2024-01-16",
            duration_s=2700.0, external_id="w1",
        )
        result = merge_activities([garmin, whoop])
        assert len(result) == 2

    def test_merged_result_sorted_by_date_desc(self):
        a1 = MockActivity(source="whoop", sport="run", activity_date="2024-01-14",
                          duration_s=1800.0, external_id="w1")
        a2 = MockActivity(source="whoop", sport="bike", activity_date="2024-01-16",
                          duration_s=3600.0, external_id="w2")
        a3 = MockActivity(source="whoop", sport="swim", activity_date="2024-01-15",
                          duration_s=2400.0, external_id="w3")
        result = merge_activities([a1, a2, a3])
        dates = [a.activity_date for a in result]
        assert dates == ["2024-01-16", "2024-01-15", "2024-01-14"]

    def test_normalization_during_merge(self):
        """Activities with non-canonical sport names should still merge."""
        garmin = MockActivity(
            source="garmin", sport="running", activity_date="2024-01-15",
            duration_s=2700.0, external_id="g1",
        )
        whoop = MockActivity(
            source="whoop", sport="running", activity_date="2024-01-15",
            duration_s=2680.0, whoop_strain=11.0, external_id="w1",
        )
        result = merge_activities([garmin, whoop])
        assert len(result) == 1
