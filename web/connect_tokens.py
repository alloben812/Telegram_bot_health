from __future__ import annotations

"""Connect token generation and WHOOP OAuth state verification."""

import hashlib
import hmac
import time
from typing import Dict, Tuple

from config import config
from database.db import create_connect_token

# In-memory store of pending WHOOP OAuth flows: user_id -> expires_at
# Cleaned up on each verify call.
_pending_whoop: Dict[int, float] = {}
_WHOOP_STATE_TTL = 600  # 10 minutes


async def generate_connect_url(user_id: int) -> str:
    """Generate a one-time connect URL for the web UI."""
    raw_token = await create_connect_token(user_id)
    base = config.WEB_BASE_URL.rstrip("/")
    return f"{base}/connect?token={raw_token}"


def generate_whoop_state(user_id: int) -> str:
    """Register a pending WHOOP OAuth flow and return user_id as state.

    WHOOP's OAuth server does not preserve complex state values —
    it only returns the raw numeric string. So we just send user_id
    and track the pending flow server-side.
    """
    _pending_whoop[user_id] = time.time() + _WHOOP_STATE_TTL
    return str(user_id)


def verify_whoop_state(state: str) -> int | None:
    """Verify WHOOP OAuth state. Returns user_id or None."""
    # Clean expired entries
    now = time.time()
    expired = [k for k, v in _pending_whoop.items() if v < now]
    for k in expired:
        del _pending_whoop[k]

    try:
        user_id = int(state)
    except ValueError:
        return None

    if user_id in _pending_whoop:
        del _pending_whoop[user_id]
        return user_id

    return None


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
