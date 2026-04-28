from __future__ import annotations

"""FastAPI routes for Web Connect UI."""

import asyncio
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import config
from database.db import (
    get_user,
    update_garmin_oauth_token,
    update_user_garmin_credentials,
    update_user_whoop_token,
    validate_connect_token,
)
from security import decrypt, decrypt_json
from web.connect_tokens import (
    generate_whoop_state,
    make_session_cookie,
    read_session_cookie,
    verify_whoop_state,
)

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

_SESSION_COOKIE = "hb_session"


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _get_user_id(session: str | None) -> int | None:
    if not session:
        return None
    return read_session_cookie(session)


async def _connection_status(user_id: int) -> dict:
    """Build status dict for Garmin/WHOOP connection."""
    user = await get_user(user_id)
    garmin_connected = False
    garmin_email = None
    whoop_connected = False

    if user:
        if user.garmin_email and user.garmin_password_enc:
            try:
                decrypt(user.garmin_password_enc)
                garmin_connected = True
                garmin_email = user.garmin_email
            except Exception:
                pass
        if user.whoop_token_enc:
            try:
                decrypt_json(user.whoop_token_enc)
                whoop_connected = True
            except Exception:
                pass

    return {
        "garmin_connected": garmin_connected,
        "garmin_email": garmin_email,
        "whoop_connected": whoop_connected,
        "garmin_last_sync": None,  # TODO: add last sync timestamp
        "whoop_last_sync": None,
    }


# ------------------------------------------------------------------ #
# Connect page
# ------------------------------------------------------------------ #


@router.get("/connect", response_class=HTMLResponse)
async def connect_page(
    request: Request,
    token: str = Query(default=""),
    hb_session: str | None = Cookie(default=None),
    success: str = Query(default=""),
    error: str = Query(default=""),
):
    # Try session cookie first (for returning after Garmin save)
    user_id = _get_user_id(hb_session)

    # If no valid session, validate the token
    if not user_id and token:
        user_id = await validate_connect_token(token)

    if not user_id:
        return templates.TemplateResponse("expired.html", {"request": request})

    status = await _connection_status(user_id)

    response = templates.TemplateResponse(
        "connect.html",
        {
            "request": request,
            "user_id": user_id,
            **status,
            "success": success,
            "error": error,
        },
    )
    # Set session cookie so user can submit forms without the token
    response.set_cookie(
        _SESSION_COOKIE,
        make_session_cookie(user_id),
        max_age=1800,
        httponly=True,
        samesite="lax",
    )
    return response


# ------------------------------------------------------------------ #
# Garmin credentials
# ------------------------------------------------------------------ #


@router.post("/connect/garmin", response_class=HTMLResponse)
async def save_garmin(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    hb_session: str | None = Cookie(default=None),
):
    user_id = _get_user_id(hb_session)
    if not user_id:
        return templates.TemplateResponse("expired.html", {"request": request})

    # Test Garmin login before saving
    try:
        from integrations.garmin import GarminClient
        gc = GarminClient()
        loop = asyncio.get_event_loop()
        client = await loop.run_in_executor(
            None, lambda: gc._create_client_for_user(email, password)
        )
    except Exception as exc:
        logger.warning("Garmin test login failed for user %d: %s", user_id, exc)
        status = await _connection_status(user_id)
        return templates.TemplateResponse(
            "connect.html",
            {
                "request": request,
                "user_id": user_id,
                **status,
                "garmin_email": email,
                "error": f"Не удалось подключиться к Garmin: {exc}",
                "success": "",
            },
        )

    await update_user_garmin_credentials(user_id, email, password)

    # Save garth token to DB so Render can reuse it (no filesystem cache)
    try:
        token_b64 = client.garth.dumps()
        await update_garmin_oauth_token(user_id, token_b64)
        logger.info("Garmin credentials + token saved via web for user %d", user_id)
    except Exception as exc:
        logger.warning("Garmin token save failed for user %d: %s", user_id, exc)
        logger.info("Garmin credentials saved via web for user %d", user_id)

    return RedirectResponse(
        url="/connect?success=Garmin+подключен",
        status_code=303,
    )


# ------------------------------------------------------------------ #
# WHOOP OAuth — initiate
# ------------------------------------------------------------------ #


@router.get("/auth/whoop")
async def whoop_auth_start(
    uid: int = Query(default=0),
    hb_session: str | None = Cookie(default=None),
):
    user_id = _get_user_id(hb_session)

    # Fallback: accept uid from query param (link from connect page)
    if not user_id and uid:
        user_id = uid

    if not user_id:
        return RedirectResponse(url="/connect?error=Сессия+истекла")

    state = await generate_whoop_state(user_id)
    params = urlencode({
        "client_id": config.WHOOP_CLIENT_ID,
        "redirect_uri": config.WHOOP_REDIRECT_URI,
        "response_type": "code",
        "scope": "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement",
        "state": state,
    })
    return RedirectResponse(url=f"{config.WHOOP_AUTH_URL}?{params}")


# ------------------------------------------------------------------ #
# WHOOP OAuth — callback
# ------------------------------------------------------------------ #


@router.get("/auth/whoop/callback", response_class=HTMLResponse)
async def whoop_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
):
    if error:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "icon": "&#10060;",
                "title": "WHOOP: ошибка авторизации",
                "message": f"WHOOP вернул ошибку: {error}. Попробуй снова из Telegram.",
            },
        )

    user_id = await verify_whoop_state(state)
    # Fallback: old Telegram flow sends state=str(user_id)
    if not user_id:
        try:
            candidate = int(state)
            from database.db import get_user
            if await get_user(candidate):
                user_id = candidate
        except (ValueError, TypeError):
            pass
    if not user_id:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "icon": "&#10060;",
                "title": "Ошибка безопасности",
                "message": "Неверный state-параметр. Попробуй снова из Telegram.",
            },
        )

    if not code:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "icon": "&#10060;",
                "title": "Нет кода авторизации",
                "message": "WHOOP не передал authorization code. Попробуй снова.",
            },
        )

    # Exchange code for token
    try:
        from integrations.whoop import WhoopClient
        wc = WhoopClient(user_id)
        token = await wc.exchange_code(code)
        await update_user_whoop_token(user_id, token)
        logger.info("WHOOP token saved via web OAuth for user %d", user_id)
    except Exception as exc:
        logger.error("WHOOP token exchange failed for user %d: %s", user_id, exc)
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "icon": "&#10060;",
                "title": "Ошибка обмена токена",
                "message": f"Не удалось завершить авторизацию WHOOP: {exc}",
            },
        )

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "icon": "&#9989;",
            "title": "WHOOP подключен!",
            "message": "Авторизация прошла успешно. Можешь вернуться в Telegram.",
        },
    )
