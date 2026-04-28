from __future__ import annotations

"""Connect token generation and WHOOP OAuth state verification."""

import hashlib
import hmac
import secrets
import time

from config import config
from database.db import create_connect_token, create_whoop_oauth_state, verify_whoop_oauth_state


async def generate_connect_url(user_id: int) -> str:
    """Generate a one-time connect URL for the web UI."""
    raw_token = await create_connect_token(user_id)
    base = config.WEB_BASE_URL.rstrip("/")
    return f"{base}/connect?token={raw_token}"


async def generate_whoop_state(user_id: int) -> str:
    """Create a random state token and persist the mapping in DB.

    WHOOP requires state >= 8 chars. We use secrets.token_urlsafe(24)
    which produces ~32 URL-safe characters. The mapping is stored in
    the database so it survives container restarts / redeploys.
    """
    state = secrets.token_urlsafe(24)
    await create_whoop_oauth_state(user_id, state)
    return state


async def verify_whoop_state(state: str) -> int | None:
    """Look up state in DB, return user_id or None. Single-use."""
    return await verify_whoop_oauth_state(state)


def make_session_cookie(user_id: int) -> str:
    """Create a signed session cookie value."""
    ts = str(int(time.time()))
    payload = f"{user_id}:{ts}"
    sig = hmac.new(
        config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{sig}"


def read_session_cookie(value: str, max_age_seconds: int = 1800) -> int | None:
    """Read and verify session cookie. Returns user_id or None."""
    parts = value.split(":")
    if len(parts) != 3:
        return None
    user_id_str, ts_str, sig = parts
    expected = hmac.new(
        config.SECRET_KEY.encode(),
        f"{user_id_str}:{ts_str}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        if int(time.time()) - int(ts_str) > max_age_seconds:
            return None
        return int(user_id_str)
    except ValueError:
        return None
