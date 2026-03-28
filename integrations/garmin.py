"""
Garmin Connect integration.

Uses the garminconnect library (backed by garth) to fetch activities, sleep,
training load, and VO2max from Garmin Connect.

## 429 rate-limit avoidance strategy

Garmin aggressively rate-limits fresh logins.  We solve this by:

1. After the first successful login we call `client.garth.dumps()` to get a
   base64 representation of the OAuth session.
2. That token is stored in the database (encrypted with Fernet).
3. On every subsequent sync we call `client.login(tokenstore_base64=token)`
   which reuses the existing session — no password exchange → no 429.
4. If the stored token is expired or invalid we fall back to a password login,
   refresh the stored token, and retry.
"""

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

import garminconnect

from config import config

logger = logging.getLogger(__name__)

# Back-off timings (seconds) for 429 / transient errors
_RETRY_DELAYS = (5, 15, 30)


def _login_with_token(email: str, token_b64: str) -> garminconnect.Garmin:
    """Login reusing a cached OAuth token — avoids fresh auth and 429."""
    client = garminconnect.Garmin(email, "")
    client.login(tokenstore_base64=token_b64)
    return client


def _login_with_password(email: str, password: str) -> garminconnect.Garmin:
    """Full OAuth login using email/password — use only when no cached token."""
    client = garminconnect.Garmin(email, password)
    client.login()
    return client


class GarminClient:
    """Async wrapper around garminconnect.

    Call `connect()` or `connect_cached()` before any data method.
    """

    def __init__(self) -> None:
        self._client: garminconnect.Garmin | None = None
        # Set after successful password login so callers can persist the token.
        self.fresh_token_b64: str | None = None

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #

    async def connect_cached(
        self, email: str, password: str, token_b64: str | None
    ) -> bool:
        """
        Try to connect using a cached OAuth token first.
        Falls back to password login if the token is missing or rejected.

        Returns True if the token was refreshed (caller should persist it).
        """
        loop = asyncio.get_event_loop()
        refreshed = False

        if token_b64:
            try:
                self._client = await loop.run_in_executor(
                    None, _login_with_token, email, token_b64
                )
                logger.info("Garmin: connected via cached OAuth token")
                return False  # no refresh needed
            except Exception as exc:
                logger.warning(
                    "Garmin cached token rejected (%s), falling back to password", exc
                )

        # Full password login
        self._client = await self._login_password_with_retry(email, password)
        # Dump the new session token so the caller can store it
        try:
            self.fresh_token_b64 = self._client.garth.dumps()
            refreshed = True
            logger.info("Garmin: obtained fresh OAuth token")
        except Exception as exc:
            logger.warning("Could not dump Garmin token: %s", exc)

        return refreshed

    async def connect(self, email: str, password: str) -> None:
        """Full password login (use connect_cached in production)."""
        self._client = await self._login_password_with_retry(email, password)
        try:
            self.fresh_token_b64 = self._client.garth.dumps()
        except Exception:
            pass

    async def _login_password_with_retry(
        self, email: str, password: str
    ) -> garminconnect.Garmin:
        loop = asyncio.get_event_loop()
        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                client = await loop.run_in_executor(
                    None, _login_with_password, email, password
                )
                return client
            except Exception as exc:
                last_exc = exc
                err_str = str(exc).lower()
                if "429" in err_str or "too many" in err_str:
                    if delay is not None:
                        logger.warning(
                            "Garmin 429 on attempt %d, retrying in %ds", attempt, delay
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise RuntimeError(
                            "Garmin rate-limited (429) after all retries. "
                            "Wait a few minutes and try again."
                        ) from exc
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    def _ensure_connected(self) -> None:
        if self._client is None:
            raise RuntimeError("GarminClient not connected. Call connect_cached() first.")

    async def _run(self, func, *args, **kwargs) -> Any:
        self._ensure_connected()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    # ------------------------------------------------------------------ #
    # Activities
    # ------------------------------------------------------------------ #

    async def get_activities(self, start: int = 0, limit: int = 10) -> list[dict]:
        return await self._run(self._client.get_activities, start, limit) or []

    async def get_activities_by_date(
        self, start_date: date, end_date: date, activity_type: str = ""
    ) -> list[dict]:
        return await self._run(
            self._client.get_activities_by_date,
            start_date.isoformat(),
            end_date.isoformat(),
            activity_type or None,
        ) or []

    async def get_last_activity(self) -> dict | None:
        acts = await self.get_activities(start=0, limit=1)
        return acts[0] if acts else None

    # ------------------------------------------------------------------ #
    # Heart rate / stress / sleep
    # ------------------------------------------------------------------ #

    async def get_heart_rates(self, target_date: date) -> dict:
        return await self._run(self._client.get_heart_rates, target_date.isoformat()) or {}

    async def get_stress_data(self, target_date: date) -> dict:
        return await self._run(self._client.get_stress_data, target_date.isoformat()) or {}

    async def get_sleep_data(self, target_date: date) -> dict:
        return await self._run(self._client.get_sleep_data, target_date.isoformat()) or {}

    # ------------------------------------------------------------------ #
    # Training metrics
    # ------------------------------------------------------------------ #

    async def get_training_status(self, target_date: date) -> dict:
        return await self._run(self._client.get_training_status, target_date.isoformat()) or {}

    async def get_training_readiness(self, target_date: date) -> dict:
        return await self._run(self._client.get_training_readiness, target_date.isoformat()) or {}

    async def get_endurance_score(self, target_date: date) -> dict:
        return await self._run(self._client.get_endurance_score, target_date.isoformat()) or {}

    # ------------------------------------------------------------------ #
    # Steps / body battery
    # ------------------------------------------------------------------ #

    async def get_steps_data(self, target_date: date) -> dict:
        return await self._run(self._client.get_steps_data, target_date.isoformat()) or {}

    async def get_body_battery(self, target_date: date) -> list[dict]:
        return await self._run(self._client.get_body_battery, target_date.isoformat()) or []

    async def get_daily_summary(self, target_date: date) -> dict:
        return await self._run(self._client.get_stats, target_date.isoformat()) or {}

    # ------------------------------------------------------------------ #
    # Weekly summary helper
    # ------------------------------------------------------------------ #

    async def get_weekly_summary(self) -> dict:
        end = date.today()
        start = end - timedelta(days=6)

        activities = await self.get_activities_by_date(start, end)
        summary = await self.get_daily_summary(end)
        sleep = await self.get_sleep_data(end)

        total_distance_m = sum(a.get("distance", 0) or 0 for a in activities)
        total_duration_s = sum(a.get("duration", 0) or 0 for a in activities)
        total_calories = sum(a.get("calories", 0) or 0 for a in activities)

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

    async def get_sport_history(self, sport: str, days: int = 30) -> list[dict]:
        end = date.today()
        start = end - timedelta(days=days - 1)
        return await self.get_activities_by_date(start, end, sport)
