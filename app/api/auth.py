from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.dependencies import (
    PLATFORM_SESSION_COOKIE,
    current_platform_session,
    get_app_settings,
)
from app.audit import record_audit_event
from app.auth.sessions import (
    create_platform_session_token,
    platform_auth_is_configured,
    platform_auth_requires_configuration,
    verify_platform_credentials,
    verify_platform_session_token,
)
from app.core.config import Settings

router = APIRouter(prefix="/auth")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class SessionResponse(BaseModel):
    auth_required: bool
    authenticated: bool
    username: str | None
    csrf_token: str | None


@router.post("/login", response_model=SessionResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SessionResponse:
    _require_platform_auth_configured(settings)
    if not verify_platform_credentials(
        settings,
        username=payload.username,
        password=payload.password,
    ):
        record_audit_event(
            request,
            event_type="auth.login_failed",
            actor_type="platform",
            actor_id=payload.username,
            outcome="failure",
            metadata={"reason": "invalid_credentials"},
        )
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    token = create_platform_session_token(settings, username=payload.username)
    session = verify_platform_session_token(settings, token)
    if session is None:
        raise HTTPException(status_code=500, detail="Could not create platform session.")

    response.set_cookie(
        PLATFORM_SESSION_COOKIE,
        token,
        max_age=settings.platform_session_ttl_seconds,
        httponly=True,
        secure=_secure_cookie(settings),
        samesite="lax",
        path="/",
    )
    request.app.state.platform_session_created = True
    record_audit_event(
        request,
        event_type="auth.login_succeeded",
        actor_type="platform",
        actor_id=session.username,
        outcome="success",
    )
    return SessionResponse(
        auth_required=True,
        authenticated=True,
        username=session.username,
        csrf_token=session.csrf_token,
    )


@router.post("/logout", response_model=SessionResponse)
def logout(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SessionResponse:
    session = current_platform_session(request)
    record_audit_event(
        request,
        event_type="auth.logout",
        actor_type="platform",
        actor_id=session.username if session is not None else None,
        outcome="success",
    )
    response.delete_cookie(PLATFORM_SESSION_COOKIE, path="/", samesite="lax")
    return _anonymous_session_response(settings)


@router.get("/session", response_model=SessionResponse)
def session_status(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SessionResponse:
    if not platform_auth_is_configured(settings):
        if platform_auth_requires_configuration(settings):
            raise HTTPException(
                status_code=503,
                detail="Platform auth is required but not configured.",
            )
        return SessionResponse(
            auth_required=False,
            authenticated=True,
            username=None,
            csrf_token=None,
        )

    session = current_platform_session(request)
    if session is None:
        return _anonymous_session_response(settings)
    return SessionResponse(
        auth_required=True,
        authenticated=True,
        username=session.username,
        csrf_token=session.csrf_token,
    )


def _require_platform_auth_configured(settings: Settings) -> None:
    if platform_auth_is_configured(settings):
        return
    detail = (
        "Platform auth is required but not configured."
        if platform_auth_requires_configuration(settings)
        else "Platform auth is not configured."
    )
    status_code = 503 if platform_auth_requires_configuration(settings) else 400
    raise HTTPException(status_code=status_code, detail=detail)


def _anonymous_session_response(settings: Settings) -> SessionResponse:
    return SessionResponse(
        auth_required=platform_auth_is_configured(settings),
        authenticated=False,
        username=None,
        csrf_token=None,
    )


def _secure_cookie(settings: Settings) -> bool:
    return settings.app_env.lower() in {"production", "staging"}
