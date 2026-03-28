"""
WHOOP API v1 integration (OAuth 2.0).

Docs: https://developer.whoop.com/api
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from config import config

logger = logging.getLogger(__name__)

_TOKEN_STORE: dict[int, dict] = {}  # user_id -> token dict


class WhoopClient:
    """Async WHOOP API client with OAuth 2.0 PKCE flow."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self._http: httpx.AsyncClient = httpx.AsyncClient(
            base_url=config.WHOOP_API_BASE,
            timeout=30.0,
        )

    # ------------------------------------------------------------------ #
    # OAuth helpers
    # ------------------------------------------------------------------ #

    def get_auth_url(self) -> str:
        """Return the WHOOP authorization URL for this user."""
        params = {
            "client_id": config.WHOOP_CLIENT_ID,
            "redirect_uri": config.WHOOP_REDIRECT_URI,
            "response_type": "code",
            "scope": "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement",
            "state": str(self.user_id),
        }
        return f"{config.WHOOP_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Exchange an authorization code for access + refresh tokens."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                config.WHOOP_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.WHOOP_REDIRECT_URI,
                    "client_id": config.WHOOP_CLIENT_ID,
                    "client_secret": config.WHOOP_CLIENT_SECRET,
                },
            )
            resp.raise_for_status()
            token = resp.json()
            self._store_token(token)
            return token

    async def refresh_token(self) -> dict:
        """Refresh the access token using the stored refresh token."""
        stored = _TOKEN_STORE.get(self.user_id)
        if not stored:
            raise RuntimeError("No token stored for user. Please re-authorize.")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                config.WHOOP_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": stored["refresh_token"],
                    "client_id": config.WHOOP_CLIENT_ID,
                    "client_secret": config.WHOOP_CLIENT_SECRET,
                },
            )
            resp.raise_for_status()
            token = resp.json()
            self._store_token(token)
            return token

    def _store_token(self, token: dict) -> None:
        expires_at = datetime.now(tz=timezone.utc) + timedelta(
            seconds=token.get("expires_in", 3600)
        )
        _TOKEN_STORE[self.user_id] = {**token, "expires_at": expires_at}

    def load_token(self, token: dict) -> None:
        """Load a previously persisted token (from DB)."""
        _TOKEN_STORE[self.user_id] = token

    def is_authorized(self) -> bool:
        return self.user_id in _TOKEN_STORE

    async def _get_headers(self) -> dict[str, str]:
        stored = _TOKEN_STORE.get(self.user_id)
        if not stored:
            raise RuntimeError("User not authorized with WHOOP.")

        expires_at = stored.get("expires_at")
        if expires_at is not None:
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if datetime.now(tz=timezone.utc) >= expires_at - timedelta(minutes=5):
                stored = await self.refresh_token()

        return {"Authorization": f"Bearer {stored['access_token']}"}

    async def _get(self, path: str, params: dict | None = None) -> Any:
        headers = await self._get_headers()
        resp = await self._http.get(path, headers=headers, params=params or {})
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Recovery
    # ------------------------------------------------------------------ #

    async def get_recovery_collection(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """Return a list of daily recovery records."""
        params: dict = {"limit": min(limit, 25)}
        if start_date:
            params["start"] = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        if end_date:
            params["end"] = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        data = await self._get("/recovery", params)
        return data.get("records", [])

    async def get_latest_recovery(self) -> dict | None:
        records = await self.get_recovery_collection(limit=1)
        return records[0] if records else None

    # ------------------------------------------------------------------ #
    # Sleep
    # ------------------------------------------------------------------ #

    async def get_sleep_collection(self, limit: int = 25) -> list[dict]:
        data = await self._get("/activity/sleep", params={"limit": min(limit, 25)})
        return data.get("records", [])

    async def get_latest_sleep(self) -> dict | None:
        records = await self.get_sleep_collection(limit=1)
        return records[0] if records else None

    # ------------------------------------------------------------------ #
    # Cycles (Strain)
    # ------------------------------------------------------------------ #

    async def get_cycle_collection(self, limit: int = 25) -> list[dict]:
        data = await self._get("/cycle", params={"limit": min(limit, 25)})
        return data.get("records", [])

    async def get_latest_cycle(self) -> dict | None:
        records = await self.get_cycle_collection(limit=1)
        return records[0] if records else None

    # ------------------------------------------------------------------ #
    # Workouts
    # ------------------------------------------------------------------ #

    async def get_workout_collection(self, limit: int = 10) -> list[dict]:
        data = await self._get("/activity/workout", params={"limit": limit})
        return data.get("records", [])

    # ------------------------------------------------------------------ #
    # Profile & body measurements
    # ------------------------------------------------------------------ #

    async def get_profile(self) -> dict:
        return await self._get("/user/profile/basic")

    async def get_body_measurement(self) -> dict:
        return await self._get("/user/measurement/body")

    # ------------------------------------------------------------------ #
    # Weekly summary
    # ------------------------------------------------------------------ #

    async def get_weekly_summary(self) -> dict:
        """Aggregate WHOOP data for the last 7 days."""
        recoveries = await self.get_recovery_collection(limit=7)
        cycles = await self.get_cycle_collection(limit=7)
        sleeps = await self.get_sleep_collection(limit=7)

        avg_recovery = (
            sum(r.get("score", {}).get("recovery_score", 0) for r in recoveries)
            / len(recoveries)
            if recoveries
            else 0
        )
        avg_hrv = (
            sum(r.get("score", {}).get("hrv_rmssd_milli", 0) for r in recoveries)
            / len(recoveries)
            if recoveries
            else 0
        )
        avg_rhr = (
            sum(r.get("score", {}).get("resting_heart_rate", 0) for r in recoveries)
            / len(recoveries)
            if recoveries
            else 0
        )
        avg_strain = (
            sum(c.get("score", {}).get("strain", 0) for c in cycles)
            / len(cycles)
            if cycles
            else 0
        )
        avg_sleep_perf = (
            sum(s.get("score", {}).get("sleep_performance_percentage", 0) for s in sleeps)
            / len(sleeps)
            if sleeps
            else 0
        )

        return {
            "recoveries": recoveries,
            "cycles": cycles,
            "sleeps": sleeps,
            "avg_recovery_score": round(avg_recovery, 1),
            "avg_hrv_ms": round(avg_hrv, 1),
            "avg_resting_hr": round(avg_rhr, 1),
            "avg_strain": round(avg_strain, 1),
            "avg_sleep_performance": round(avg_sleep_perf, 1),
        }
