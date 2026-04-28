"""Tests for integrations/whoop.py — WHOOP client with mocked httpx."""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from integrations.whoop import WhoopClient, _TOKEN_STORE, WHOOP_SPORTS


class TestWhoopSportsMap:
    def test_running(self):
        assert WHOOP_SPORTS[0] == "running"

    def test_cycling(self):
        assert WHOOP_SPORTS[1] == "cycling"

    def test_swimming(self):
        assert WHOOP_SPORTS[16] == "swimming"

    def test_strength(self):
        assert WHOOP_SPORTS[44] == "strength"

    def test_unknown_id(self):
        assert 999 not in WHOOP_SPORTS


class TestWhoopClientAuth:
    def setup_method(self):
        _TOKEN_STORE.clear()

    def test_not_authorized_initially(self):
        wc = WhoopClient(user_id=12345)
        assert not wc.is_authorized()

    def test_load_token(self):
        wc = WhoopClient(user_id=12345)
        wc.load_token({
            "access_token": "test_access",
            "refresh_token": "test_refresh",
            "expires_at": (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        assert wc.is_authorized()

    def test_store_token_sets_expires_at(self):
        wc = WhoopClient(user_id=12345)
        wc._store_token({"access_token": "a", "refresh_token": "r", "expires_in": 3600})
        stored = _TOKEN_STORE[12345]
        assert "expires_at" in stored
        assert stored["expires_at"] > datetime.now(tz=timezone.utc)

    def teardown_method(self):
        _TOKEN_STORE.clear()


class TestWhoopClientAPI:
    def setup_method(self):
        _TOKEN_STORE.clear()
        self.wc = WhoopClient(user_id=12345)
        self.wc.load_token({
            "access_token": "test_access",
            "refresh_token": "test_refresh",
            "expires_at": (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat(),
        })

    async def test_get_latest_recovery(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [{
                "score": {
                    "recovery_score": 72.0,
                    "hrv_rmssd_milli": 48.5,
                    "resting_heart_rate": 52.0,
                },
            }],
        }

        self.wc._http = AsyncMock()
        self.wc._http.get = AsyncMock(return_value=mock_response)

        result = await self.wc.get_latest_recovery()
        assert result is not None
        assert result["score"]["recovery_score"] == 72.0

    async def test_get_latest_sleep(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [{
                "score": {"sleep_performance_percentage": 85.0},
            }],
        }

        self.wc._http = AsyncMock()
        self.wc._http.get = AsyncMock(return_value=mock_response)

        result = await self.wc.get_latest_sleep()
        assert result is not None
        assert result["score"]["sleep_performance_percentage"] == 85.0

    async def test_get_workout_collection(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [
                {"id": 1, "sport_id": 0, "score": {"strain": 12.3}},
                {"id": 2, "sport_id": 1, "score": {"strain": 8.5}},
            ],
        }

        self.wc._http = AsyncMock()
        self.wc._http.get = AsyncMock(return_value=mock_response)

        result = await self.wc.get_workout_collection()
        assert len(result) == 2
        assert result[0]["score"]["strain"] == 12.3

    async def test_get_empty_recovery(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"records": []}

        self.wc._http = AsyncMock()
        self.wc._http.get = AsyncMock(return_value=mock_response)

        result = await self.wc.get_latest_recovery()
        assert result is None

    async def test_404_returns_empty(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {}

        self.wc._http = AsyncMock()
        self.wc._http.get = AsyncMock(return_value=mock_response)

        # _get returns {} on 404
        result = await self.wc._get("/recovery")
        assert result == {}

    async def test_exchange_code(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            token = await self.wc.exchange_code("test_code")
            assert token["access_token"] == "new_access"
            assert self.wc.is_authorized()

    def teardown_method(self):
        _TOKEN_STORE.clear()
