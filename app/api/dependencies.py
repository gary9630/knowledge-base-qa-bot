from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.answer.providers import AnswerProvider, create_answer_provider
from app.audit import fingerprint_secret, record_audit_event
from app.auth.sessions import (
    PlatformSession,
    platform_auth_is_configured,
    platform_auth_requires_configuration,
    verify_platform_session_token,
)
from app.core.config import Settings
from app.core.database import SessionLocal
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider
from app.source_access import SourcePrincipal, source_principal_for_session

SessionFactory = Callable[[], Session]
PLATFORM_SESSION_COOKIE = "kb_platform_session"
CSRF_HEADER_NAME = "X-KB-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings

    settings = Settings()
    request.app.state.settings = settings
    return settings


def get_indexing_session_factory(request: Request) -> SessionFactory:
    session_factory = getattr(request.app.state, "session_factory", None)
    if callable(session_factory):
        return cast(SessionFactory, session_factory)

    return cast(SessionFactory, SessionLocal)


def get_request_db_session(request: Request) -> Iterator[Session]:
    with get_indexing_session_factory(request)() as session:
        yield session


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    embedding_provider = getattr(request.app.state, "embedding_provider", None)
    if embedding_provider is not None:
        return cast(EmbeddingProvider, embedding_provider)

    embedding_provider = create_embedding_provider(get_app_settings(request))
    request.app.state.embedding_provider = embedding_provider
    return embedding_provider


def get_answer_provider(request: Request) -> AnswerProvider:
    answer_provider = getattr(request.app.state, "answer_provider", None)
    if answer_provider is not None:
        return cast(AnswerProvider, answer_provider)

    answer_provider = create_answer_provider(get_app_settings(request))
    request.app.state.answer_provider = answer_provider
    return answer_provider


def require_admin_access(
    request: Request,
    admin_key: str | None = Header(default=None, alias="X-KB-Admin-Key"),
) -> None:
    settings = get_app_settings(request)
    if settings.admin_api_key:
        if admin_key != settings.admin_api_key:
            record_audit_event(
                request,
                event_type="admin.access_denied",
                actor_type="admin",
                actor_id=fingerprint_secret(admin_key) if admin_key else None,
                outcome="failure",
                metadata={
                    "reason": "invalid_admin_key" if admin_key else "missing_admin_key"
                },
            )
            raise HTTPException(status_code=401, detail="Admin API key is required.")
        record_audit_event(
            request,
            event_type="admin.access_granted",
            actor_type="admin",
            actor_id=fingerprint_secret(settings.admin_api_key),
            outcome="success",
        )
        return

    if settings.app_env.lower() in {"production", "staging"}:
        record_audit_event(
            request,
            event_type="admin.access_denied",
            actor_type="admin",
            outcome="failure",
            metadata={"reason": "missing_admin_api_key_config"},
        )
        raise HTTPException(
            status_code=503,
            detail="KB_ADMIN_API_KEY is required for admin endpoints.",
        )

    record_audit_event(
        request,
        event_type="admin.access_granted",
        actor_type="admin",
        actor_id="development",
        outcome="success",
        metadata={"reason": "development_admin_access"},
    )


def current_platform_session(request: Request) -> PlatformSession | None:
    settings = get_app_settings(request)
    token = request.cookies.get(PLATFORM_SESSION_COOKIE)
    if not token:
        return None
    return verify_platform_session_token(settings, token)


def require_platform_access(
    request: Request,
    csrf_token: str | None = Header(default=None, alias=CSRF_HEADER_NAME),
) -> PlatformSession | None:
    settings = get_app_settings(request)
    if not platform_auth_is_configured(settings):
        if platform_auth_requires_configuration(settings):
            raise HTTPException(
                status_code=503,
                detail="Platform auth is required but not configured.",
            )
        return None

    session = current_platform_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Platform login is required.")

    if request.method.upper() not in SAFE_METHODS and csrf_token != session.csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token is required.")

    return session


def get_source_principal(
    request: Request,
    session: Annotated[PlatformSession | None, Depends(require_platform_access)],
) -> SourcePrincipal:
    return source_principal_for_session(get_app_settings(request), session)
