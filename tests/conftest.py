"""Shared test fixtures.

Environment variables are set BEFORE any project module is imported
so that config.py, security.py and database.db pick up test values.
"""

from __future__ import annotations

import json
import os

# ── Set env vars before any project imports ──────────────────────────
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ADMIN_TELEGRAM_ID", "12345")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("WHOOP_CLIENT_ID", "test-whoop-id")
os.environ.setdefault("WHOOP_CLIENT_SECRET", "test-whoop-secret")
os.environ.setdefault("WHOOP_REDIRECT_URI", "http://localhost:8000/auth/whoop/callback")
os.environ.setdefault("WEB_BASE_URL", "http://localhost:8000")

import pytest
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from database.models import Base


# ── Database fixtures ────────────────────────────────────────────────


@pytest.fixture
async def db_engine():
    """Create a fresh in-memory SQLite engine with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def patch_db(db_engine, monkeypatch):
    """Patch database.db to use the test in-memory engine."""
    import database.db as db_mod

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "engine", db_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", session_factory)
    return db_engine


# ── Mock data factories ──────────────────────────────────────────────


@dataclass
class MockSnapshot:
    """Lightweight snapshot for testing _build_context."""
    whoop_recovery_score: Optional[float] = None
    whoop_hrv_ms: Optional[float] = None
    whoop_resting_hr: Optional[float] = None
    whoop_strain: Optional[float] = None
    whoop_sleep_performance: Optional[float] = None
    whoop_spo2: Optional[float] = None
    whoop_skin_temp: Optional[float] = None
    whoop_respiratory_rate: Optional[float] = None
    whoop_sleep_duration_h: Optional[float] = None
    garmin_training_readiness: Optional[int] = None
    garmin_body_battery_end: Optional[int] = None
    garmin_steps: Optional[int] = None
    garmin_stress_avg: Optional[int] = None
    garmin_active_calories: Optional[int] = None


@dataclass
class MockActivity:
    """Lightweight activity for testing _build_context and merge_activities."""
    source: str = "whoop"
    sport: str = "run"
    activity_date: str = ""
    duration_s: Optional[float] = None
    distance_m: Optional[float] = None
    calories: Optional[int] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    whoop_strain: Optional[float] = None
    avg_pace_s_per_km: Optional[float] = None
    avg_power_w: Optional[float] = None
    avg_cadence: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    external_id: Optional[str] = None


@dataclass
class MockProfile:
    max_hr: Optional[int] = None


@pytest.fixture
def today_str():
    return date.today().isoformat()


@pytest.fixture
def make_snapshots():
    """Factory to create N snapshots with declining dates and configurable metrics."""

    def _make(
        n: int = 7,
        recovery_base: float = 60.0,
        hrv_base: float = 45.0,
        strain_base: float = 10.0,
        sleep_perf_base: float = 80.0,
        sleep_dur_base: float = 7.5,
    ) -> list[MockSnapshot]:
        snapshots = []
        for i in range(n):
            snapshots.append(MockSnapshot(
                whoop_recovery_score=recovery_base + (n - i) * 2,  # newer = lower
                whoop_hrv_ms=hrv_base + (n - i),
                whoop_resting_hr=55.0,
                whoop_strain=strain_base + i * 0.5,
                whoop_sleep_performance=sleep_perf_base,
                whoop_sleep_duration_h=sleep_dur_base,
            ))
        return snapshots

    return _make


@pytest.fixture
def make_activities():
    """Factory to create activities list."""

    def _make(specs: list[dict]) -> list[MockActivity]:
        return [MockActivity(**s) for s in specs]

    return _make


# ── WHOOP API sample responses ───────────────────────────────────────


@pytest.fixture
def sample_whoop_recovery():
    return {
        "score": {
            "recovery_score": 72.0,
            "resting_heart_rate": 52.0,
            "hrv_rmssd_milli": 48.5,
            "spo2_percentage": 97.0,
            "skin_temp_celsius": 33.2,
        },
        "cycle_id": 12345,
    }


@pytest.fixture
def sample_whoop_sleep():
    return {
        "score": {
            "sleep_performance_percentage": 85.0,
            "respiratory_rate": 15.2,
            "stage_summary": {
                "total_in_bed_time_milli": 28800000,
                "total_light_sleep_time_milli": 14400000,
                "total_slow_wave_sleep_time_milli": 7200000,
                "total_rem_sleep_time_milli": 5400000,
                "total_awake_time_milli": 1800000,
                "sleep_cycle_count": 4,
            },
            "sleep_efficiency_percentage": 92.0,
        },
    }


@pytest.fixture
def sample_whoop_workout():
    return {
        "id": 99001,
        "sport_id": 0,
        "sport_name": "Running",
        "start": "2024-01-15T08:00:00.000Z",
        "end": "2024-01-15T08:45:00.000Z",
        "score": {
            "strain": 12.3,
            "average_heart_rate": 155,
            "max_heart_rate": 178,
            "kilojoule": 1800.0,
            "distance_meter": 8500.0,
        },
    }


@pytest.fixture
def sample_garmin_activity():
    return {
        "activityId": 88001,
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2024-01-15 08:02:00",
        "duration": 2680.0,
        "distance": 8450.0,
        "averageHR": 153,
        "maxHR": 176,
        "calories": 430,
        "averageSpeed": 3.15,
        "elevationGain": 45.0,
    }


# ── AI mock ──────────────────────────────────────────────────────────


VALID_RECOMMENDATION_JSON = json.dumps({
    "readiness_score": 72,
    "status_label": "Умеренная готовность",
    "main_recommendation": "Сегодня подходящий день для базовой аэробной тренировки",
    "planned_workout": {
        "sport": "run",
        "title": "Лёгкий бег в зоне 2",
        "duration_minutes": 45,
        "intensity": "z2",
        "blocks": [
            {
                "title": "Разминка",
                "duration_minutes": 10,
                "target_hr_zone": "z1",
                "target_hr_range": "120-135",
                "notes": "Лёгкий бег трусцой",
            },
            {
                "title": "Основная часть",
                "duration_minutes": 25,
                "target_hr_zone": "z2",
                "target_hr_range": "135-150",
                "notes": None,
            },
            {
                "title": "Заминка",
                "duration_minutes": 10,
                "target_hr_zone": "z1",
                "target_hr_range": None,
                "notes": "Шаг + растяжка",
            },
        ],
    },
    "reasoning": ["HRV выше 7-дневного среднего", "Восстановление 72%"],
    "avoid": ["Интервалы в зоне 4-5"],
    "control": ["Если ЧСС > 155 — снизить темп"],
    "confidence": "medium",
    "data_gaps": ["Нет данных Garmin"],
})


class MockAIProvider:
    """Mock AI provider that returns a fixed response."""

    def __init__(self, response: str = VALID_RECOMMENDATION_JSON):
        self.response = response
        self.calls: list[dict] = []

    async def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return self.response


@pytest.fixture
def mock_ai_provider():
    return MockAIProvider()
