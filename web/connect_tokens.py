from __future__ import annotations

"""Connect token generation and WHOOP OAuth state signing."""

import hashlib
import hmac

from config import config
from database.db import create_connect_token


async def generate_connect_url(user_id: int) -> str:
    """Generate a one-time connect URL for the web UI."""
    raw_token = await create_connect_token(user_id)
    base = config.WEB_BASE_URL.rstrip("/")
    return f"{base}/connect?token={raw_token}"


def generate_whoop_state(user_id: int) -> str:
    """Create HMAC-signed state for WHOOP OAuth callback."""
    msg = str(user_id).encode()
    sig = hmac.new(config.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()
    return f"{user_id}:{sig}"


def verify_whoop_state(state: str) -> int | None:
    """Verify HMAC-signed state. Returns user_id or None."""
    parts = state.split(":", 1)
    if len(parts) != 2:
        return None
    user_id_str, sig = parts
    try:
        user_id = int(user_id_str)
    except ValueError:
        return None
    expected = hmac.new(
        config.SECRET_KEY.encode(), user_id_str.encode(), hashlib.sha256
    ).hexdigest()
    if hmac.compare_digest(sig, expected):
        return user_id
    return None


def make_session_cookie(user_id: int) -> str:
    """Create a signed session cookie value."""
    import time
    ts = str(int(time.time()))
    payload = f"{user_id}:{ts}"
    sig = hmac.new(
        config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{sig}"


def read_session_cookie(value: str, max_age_seconds: int = 1800) -> int | None:
    """Read and verify session cookie. Returns user_id or None."""
    import time
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
