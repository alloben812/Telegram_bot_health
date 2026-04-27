"""
Garmin Connect integration.

Uses garminconnect 0.3.x (backed by curl_cffi — browser-level TLS fingerprinting)
to fetch activities, sleep, training load, and daily stats from Garmin Connect.

Token caching strategy:
  - After the first SSO login, tokens are saved to .garth_cache/<email>/
  - On subsequent calls, tokens are loaded from cache — no SSO hit
  - The library auto-refreshes the OAuth2 token when needed
  - A cooldown file prevents hammering sso.garmin.com after a 429
"""

from __future__ import annotations
import asyncio
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import garminconnect

logger = logging.getLogger(__name__)

_GARTH_CACHE_DIR = Path(__file__).parent.parent / ".garth_cache"
_LOGIN_COOLDOWN_S = 3600


def _cache_dir_for(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    return _GARTH_CACHE_DIR / safe


def _cooldown_file_for(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    return _GARTH_CACHE_DIR / f".cooldown_{safe}"


def _check_cooldown(email: str) -> int:
    cf = _cooldown_file_for(email)
    if not cf.exists():
        return 0
    try:
        remaining = int(_LOGIN_COOLDOWN_S - (time.time() - float(cf.read_text())))
        return max(0, remaining)
    except Exception:
        return 0


def _set_cooldown(email: str) -> None:
    cf = _cooldown_file_for(email)
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(str(time.time()))


def _clear_cooldown(email: str) -> None:
    try:
        _cooldown_file_for(email).unlink(missing_ok=True)
    except Exception:
        pass


class GarminClient:
    """Async wrapper around garminconnect 0.3.x.

    Call connect_cached() before any data method.
    """

    def __init__(self) -> None:
        self._client: garminconnect.Garmin | None = None

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #

    async def connect_cached(
        self, email: str, password: str, token_b64: str | None = None
    ) -> bool:
        """Connect using cached file tokens (falls back to SSO login).

        Returns False — token management is fully handled by the library.
        """
        loop = asyncio.get_event_loop()
        self._client = await loop.run_in_executor(
            None, self._create_client_for_user, email, password
        )
        return False

    def _create_client_for_user(self, email: str, password: str) -> garminconnect.Garmin:
        """Login to Garmin, reusing cached tokens when available.

        garminconnect 0.3.x with curl_cffi handles browser-level TLS fingerprinting
        to bypass Garmin bot detection.  login(tokenstore=path) auto-loads tokens
        if cached, does full SSO login otherwise, and auto-saves after SSO.
        """
        wait = _check_cooldown(email)
        if wait > 0:
            mins = wait // 60
            raise RuntimeError(
                f"Garmin SSO временно заблокирован (429). "
                f"Подожди ещё {mins} мин и попробуй снова."
            )

        cache_dir = _cache_dir_for(email)
        cache_dir.mkdir(parents=True, exist_ok=True)

        has_cache = any(cache_dir.glob("*.json"))

        client = garminconnect.Garmin(email, password)
        try:
            if has_cache:
                client.login(tokenstore=str(cache_dir))
                logger.info("Garmin: connected for %s (cached tokens)", email)
            else:
                client.login()
                try:
                    client.garth.dump(str(cache_dir))
                    logger.info("Garmin: SSO login ok for %s, tokens saved", email)
                except Exception:
                    logger.warning("Garmin: could not save tokens for %s", email)
            _clear_cooldown(email)
            return client
        except Exception as exc:
            exc_str = str(exc)
            is_429 = (
                isinstance(exc, garminconnect.GarminConnectTooManyRequestsError)
                or "429" in exc_str
                or "Too Many Requests" in exc_str
            )
            is_auth = (
                isinstance(exc, garminconnect.GarminConnectAuthenticationError)
                or "401" in exc_str
                or "authentication" in exc_str.lower()
            )
            if is_429:
                _set_cooldown(email)
                raise RuntimeError(
                    "Garmin SSO вернул 429 (Too Many Requests). "
                    "Подожди 60 мин перед следующей попыткой."
                ) from exc
            if is_auth:
                raise RuntimeError(
                    f"Garmin: ошибка авторизации — проверь email и пароль.\n{exc}"
                ) from exc
            raise RuntimeError(f"Garmin: ошибка подключения — {exc}") from exc

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
