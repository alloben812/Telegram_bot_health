"""
Garmin Connect integration.

Uses the garminconnect library to fetch activities, sleep,
training load, and VO2max from Garmin Connect.

Token caching strategy:
  - On first login, garth tokens are saved to .garth_cache/<email>/
  - On subsequent calls, tokens are loaded from cache — no SSO request
  - garth auto-refreshes OAuth2 access token using the refresh token
  - Only when refresh token itself expires is a new SSO login needed
  - A cooldown file prevents hammering sso.garmin.com after a 429
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import garminconnect

from config import config

logger = logging.getLogger(__name__)

# Directory to cache Garmin auth tokens — avoids re-login on every sync
_GARTH_CACHE_DIR = Path(os.path.dirname(os.path.dirname(__file__))) / ".garth_cache"

# Seconds to wait between SSO login attempts (Garmin bans for ~60 min on 429)
_LOGIN_COOLDOWN_S = 3600


def _cache_dir_for(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    return _GARTH_CACHE_DIR / safe


def _cooldown_file_for(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    return _GARTH_CACHE_DIR / f".cooldown_{safe}"


def _check_cooldown(email: str) -> int:
    """Return seconds remaining in cooldown, or 0 if clear."""
    cf = _cooldown_file_for(email)
    if not cf.exists():
        return 0
    try:
        last_attempt = float(cf.read_text())
        remaining = int(_LOGIN_COOLDOWN_S - (time.time() - last_attempt))
        return max(0, remaining)
    except Exception:
        return 0


def _set_cooldown(email: str) -> None:
    cf = _cooldown_file_for(email)
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(str(time.time()))


def _clear_cooldown(email: str) -> None:
    cf = _cooldown_file_for(email)
    try:
        cf.unlink(missing_ok=True)
    except Exception:
        pass


def _oauth2_token_valid(cache_dir: Path) -> bool:
    """Check oauth2 token expiry from file without making any HTTP request."""
    token_file = cache_dir / "oauth2_token.json"
    if not token_file.exists():
        return False
    try:
        data = json.loads(token_file.read_text())
        expires_at = data.get("expires_at", 0)
        # Consider valid if >5 minutes remain, OR if refresh_token exists
        # (garth will auto-refresh using it)
        if time.time() < float(expires_at) - 300:
            return True
        return bool(data.get("refresh_token"))
    except Exception:
        return False


class GarminClient:
    """Wrapper around garminconnect with async support."""

    def __init__(self) -> None:
        self._client: garminconnect.Garmin | None = None

    async def connect(self) -> None:
        """Authenticate and establish a session with Garmin Connect."""
        loop = asyncio.get_event_loop()
        try:
            self._client = await loop.run_in_executor(None, self._create_client)
            logger.info("Connected to Garmin Connect")
        except Exception as exc:
            logger.error("Failed to connect to Garmin Connect: %s", exc)
            raise

    def _create_client_for_user(self, email: str, password: str) -> garminconnect.Garmin:
        """Return a garminconnect client, using cached tokens whenever possible.

        Strategy (no unnecessary SSO hits):
        1. If cache dir exists and has a refresh token → load it, trust it.
           garth will silently refresh the access token when making API calls.
        2. If no cache / tokens unreadable → check cooldown, then do full login.
        3. On 429 → set cooldown and raise RuntimeError with wait time.
        """
        cache_dir = _cache_dir_for(email)
        client = garminconnect.Garmin(email, password)

        # ---- Step 1: try loading from cache ----
        if _oauth2_token_valid(cache_dir):
            try:
                client.garth.load(str(cache_dir))
                logger.info("Garmin: loaded cached session for %s", email)
                return client  # garth handles refresh lazily
            except Exception as exc:
                logger.warning("Garmin: cache load failed (%s), will re-login", exc)

        # ---- Step 2: check cooldown before hitting SSO ----
        wait = _check_cooldown(email)
        if wait > 0:
            mins = wait // 60
            raise RuntimeError(
                f"Garmin SSO временно заблокирован (429). "
                f"Подожди ещё {mins} мин и попробуй снова."
            )

        # ---- Step 3: full SSO login ----
        logger.info("Garmin: performing SSO login for %s", email)
        _set_cooldown(email)  # set before attempt so parallel calls are blocked
        try:
            client.login()
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str:
                raise RuntimeError(
                    f"Garmin SSO вернул 429 (Too Many Requests). "
                    f"Подожди 60 мин перед следующей попыткой. "
                    f"Это ограничение Garmin, не наша ошибка."
                ) from exc
            raise

        # Success — save tokens and clear cooldown
        cache_dir.mkdir(parents=True, exist_ok=True)
        client.garth.dump(str(cache_dir))
        _clear_cooldown(email)
        logger.info("Garmin: SSO login succeeded, tokens cached for %s", email)
        return client

    def _create_client(self) -> garminconnect.Garmin:
        return self._create_client_for_user(config.GARMIN_EMAIL, config.GARMIN_PASSWORD)

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
