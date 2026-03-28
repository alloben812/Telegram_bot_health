"""
Garmin Connect integration.

Uses the garminconnect library to fetch activities, sleep,
training load, and VO2max from Garmin Connect.
"""

from __future__ import annotations
import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import garminconnect

from config import config

logger = logging.getLogger(__name__)


class GarminClient:
    """Wrapper around garminconnect with async support."""

    def __init__(self) -> None:
        self._client: garminconnect.Garmin | None = None

    async def connect(self) -> None:
        """Authenticate and establish a session with Garmin Connect."""
        loop = asyncio.get_event_loop()
        try:
            self._client = await loop.run_in_executor(
                None, self._create_client
            )
            logger.info("Connected to Garmin Connect")
        except Exception as exc:
            logger.error("Failed to connect to Garmin Connect: %s", exc)
            raise

    def _create_client(self) -> garminconnect.Garmin:
        client = garminconnect.Garmin(
            config.GARMIN_EMAIL, config.GARMIN_PASSWORD
        )
        client.login()
        return client

    def _ensure_connected(self) -> None:
        if self._client is None:
            raise RuntimeError("Not connected to Garmin. Call connect() first.")

    async def _run(self, func, *args, **kwargs) -> Any:
        """Run a blocking garminconnect call in the thread pool."""
        self._ensure_connected()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    # ------------------------------------------------------------------ #
    # Activities
    # ------------------------------------------------------------------ #

    async def get_activities(
        self, start: int = 0, limit: int = 10
    ) -> list[dict]:
        """Return recent activities sorted newest-first."""
        data = await self._run(
            self._client.get_activities, start, limit
        )
        return data or []

    async def get_activities_by_date(
        self,
        start_date: date,
        end_date: date,
        activity_type: str = "",
    ) -> list[dict]:
        """Return activities between two dates, optionally filtered by type.

        activity_type examples: 'running', 'cycling', 'swimming', 'strength_training'
        """
        data = await self._run(
            self._client.get_activities_by_date,
            start_date.isoformat(),
            end_date.isoformat(),
            activity_type or None,
        )
        return data or []

    async def get_last_activity(self) -> dict | None:
        """Return the most recent activity or None."""
        activities = await self.get_activities(start=0, limit=1)
        return activities[0] if activities else None

    # ------------------------------------------------------------------ #
    # Heart rate & stress
    # ------------------------------------------------------------------ #

    async def get_heart_rates(self, target_date: date) -> dict:
        """Return heart rate data for a specific date."""
        return await self._run(
            self._client.get_heart_rates, target_date.isoformat()
        ) or {}

    async def get_stress_data(self, target_date: date) -> dict:
        """Return stress score data for a specific date."""
        return await self._run(
            self._client.get_stress_data, target_date.isoformat()
        ) or {}

    # ------------------------------------------------------------------ #
    # Sleep
    # ------------------------------------------------------------------ #

    async def get_sleep_data(self, target_date: date) -> dict:
        """Return sleep data for a specific date (previous night)."""
        return await self._run(
            self._client.get_sleep_data, target_date.isoformat()
        ) or {}

    # ------------------------------------------------------------------ #
    # Training & fitness metrics
    # ------------------------------------------------------------------ #

    async def get_training_status(self, target_date: date) -> dict:
        """Return training status (load, readiness) for a specific date."""
        return await self._run(
            self._client.get_training_status, target_date.isoformat()
        ) or {}

    async def get_training_readiness(self, target_date: date) -> dict:
        """Return training readiness score."""
        return await self._run(
            self._client.get_training_readiness, target_date.isoformat()
        ) or {}

    async def get_hill_score(self, target_date: date) -> dict:
        return await self._run(
            self._client.get_hill_score, target_date.isoformat()
        ) or {}

    async def get_endurance_score(self, target_date: date) -> dict:
        return await self._run(
            self._client.get_endurance_score, target_date.isoformat()
        ) or {}

    # ------------------------------------------------------------------ #
    # Steps & body battery
    # ------------------------------------------------------------------ #

    async def get_steps_data(self, target_date: date) -> dict:
        return await self._run(
            self._client.get_steps_data, target_date.isoformat()
        ) or {}

    async def get_body_battery(self, target_date: date) -> list[dict]:
        return await self._run(
            self._client.get_body_battery, target_date.isoformat()
        ) or []

    async def get_daily_summary(self, target_date: date) -> dict:
        """Convenience: fetch all key daily metrics in one call."""
        return await self._run(
            self._client.get_stats, target_date.isoformat()
        ) or {}

    # ------------------------------------------------------------------ #
    # Weekly summary helper
    # ------------------------------------------------------------------ #

    async def get_weekly_summary(self) -> dict:
        """Aggregate activities and metrics for the last 7 days."""
        end = date.today()
        start = end - timedelta(days=6)

        activities = await self.get_activities_by_date(start, end)
        summary = await self.get_daily_summary(end)
        sleep = await self.get_sleep_data(end)

        total_distance_m = sum(
            a.get("distance", 0) or 0 for a in activities
        )
        total_duration_s = sum(
            a.get("duration", 0) or 0 for a in activities
        )
        total_calories = sum(
            a.get("calories", 0) or 0 for a in activities
        )

        sport_counts: dict[str, int] = {}
        for act in activities:
            sport = act.get("activityType", {}).get("typeKey", "other")
            sport_counts[sport] = sport_counts.get(sport, 0) + 1

        return {
            "period": f"{start} — {end}",
            "total_activities": len(activities),
            "sport_breakdown": sport_counts,
            "total_distance_km": round(total_distance_m / 1000, 1),
            "total_duration_h": round(total_duration_s / 3600, 1),
            "total_calories": total_calories,
            "activities": activities,
            "daily_summary": summary,
            "sleep": sleep,
        }

    async def get_sport_history(
        self, sport: str, days: int = 30
    ) -> list[dict]:
        """Return activities for a specific sport over the last N days."""
        end = date.today()
        start = end - timedelta(days=days - 1)
        return await self.get_activities_by_date(start, end, sport)


# Module-level singleton
garmin_client = GarminClient()
