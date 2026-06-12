from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.answer.providers import AnswerProvider, create_answer_provider
from app.answer.query_router import QueryRouter, create_query_router
from app.audit import fingerprint_secret, record_audit_event
from app.auth.sessions import (
    ROLE_ADMIN,
    PlatformSession,
    platform_auth_is_configured,
    platform_auth_requires_configuration,
    verify_platform_session_token,
)
from app.core.config import Settings
from app.core.database import SessionLocal
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider
from app.runtime_settings import apply_runtime_overrides, safe_load_runtime_overrides
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


def get_runtime_overrides(request: Request) -> dict[str, object]:
    """Admin-tunable overrides, cached on app state after the first DB read."""
    cached = getattr(request.app.state, "runtime_overrides", None)
    if isinstance(cached, dict):
        return cached

    try:
        with get_indexing_session_factory(request)() as session:
            overrides = safe_load_runtime_overrides(session)
    except Exception:
        # Missing table (pre-migration) or transient DB issue: fall back to env
        # settings; the next admin save repopulates the cache.
        overrides = {}
    request.app.state.runtime_overrides = overrides
    return overrides


def set_runtime_overrides(request: Request, overrides: dict[str, object]) -> None:
    request.app.state.runtime_overrides = dict(overrides)


def get_effective_settings(request: Request) -> Settings:
    """Env-derived settings with any admin runtime overrides layered on top."""
    return apply_runtime_overrides(get_app_settings(request), get_runtime_overrides(request))


def _answer_provider_build_key(settings: Settings) -> tuple[object, ...]:
    return (
        settings.answer_provider,
        settings.openai_chat_model,
        settings.openai_chat_max_completion_tokens,
        settings.openai_chat_temperature,
    )


def get_answer_provider(request: Request, *, model: str | None = None) -> AnswerProvider:
    """Answer provider honouring runtime overrides.

    ``model`` overrides the chat model for this caller (difficulty routing);
    providers are cached per build key so easy/hard models coexist.
    """
    app_state = request.app.state
    injected = getattr(app_state, "answer_provider", None)
    if injected is not None and getattr(app_state, "answer_provider_injected", False):
        return cast(AnswerProvider, injected)

    effective = get_effective_settings(request)
    if model:
        effective = effective.model_copy(update={"openai_chat_model": model})
    build_key = _answer_provider_build_key(effective)
    cache = getattr(app_state, "answer_provider_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        app_state.answer_provider_cache = cache
    cached = cache.get(build_key)
    if cached is not None:
        return cast(AnswerProvider, cached)

    answer_provider = create_answer_provider(effective)
    cache[build_key] = answer_provider
    if model is None:
        # Keep the app.state alias pointing at the current default-model
        # provider for non-request consumers (background worker wiring).
        app_state.answer_provider = answer_provider
    return answer_provider


def get_query_router(request: Request) -> QueryRouter:
    """Query guardrail/difficulty router, rebuilt when runtime overrides change."""
    app_state = request.app.state
    injected = getattr(app_state, "query_router", None)
    if injected is not None and getattr(app_state, "query_router_injected", False):
        return cast(QueryRouter, injected)

    effective = get_effective_settings(request)
    build_key = (
        effective.query_router_enabled,
        effective.answer_provider,
        effective.openai_router_model,
    )
    cached = getattr(app_state, "query_router_cached", None)
    if cached is not None and getattr(app_state, "query_router_key", None) == build_key:
        return cast(QueryRouter, cached)

    router = create_query_router(effective)
    app_state.query_router_cached = router
    app_state.query_router_key = build_key
    return router


def require_admin_access(
    request: Request,
    admin_key: str | None = Header(default=None, alias="X-KB-Admin-Key"),
    csrf_token: str | None = Header(default=None, alias=CSRF_HEADER_NAME),
) -> None:
    settings = get_app_settings(request)

    # A logged-in admin session grants admin access without the shared API key.
    # Unsafe methods still require the session's CSRF token.
    session = current_platform_session(request)
    if session is not None and session.role == ROLE_ADMIN:
        if request.method.upper() in SAFE_METHODS or csrf_token == session.csrf_token:
            record_audit_event(
                request,
                event_type="admin.access_granted",
                actor_type="admin",
                actor_id=session.username,
                outcome="success",
                metadata={"reason": "admin_session"},
            )
            return

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
