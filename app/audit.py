from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

from starlette.requests import Request

from app.core.database import SessionLocal
from app.models.tables import AuditEvent

logger = logging.getLogger("app.audit")


@dataclass(frozen=True)
class AuditEventInput:
    event_type: str
    actor_type: str
    actor_id: str | None
    outcome: str
    request_id: str | None
    method: str | None
    path: str | None
    client_host: str | None
    user_agent: str | None
    resource_type: str | None
    resource_id: str | None
    metadata: dict[str, object] = field(default_factory=dict)


AuditRecorder = Callable[[AuditEventInput], None]


def record_audit_event(
    request: Request,
    *,
    event_type: str,
    actor_type: str,
    outcome: str,
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    event = AuditEventInput(
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        outcome=outcome,
        request_id=_request_id(request),
        method=request.method,
        path=request.url.path,
        client_host=_client_host(request),
        user_agent=request.headers.get("user-agent"),
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=dict(metadata or {}),
    )
    recorder = getattr(request.app.state, "audit_recorder", None)
    if callable(recorder):
        cast(AuditRecorder, recorder)(event)
        return

    try:
        session_factory = getattr(request.app.state, "session_factory", None)
        if not callable(session_factory):
            session_factory = SessionLocal
        with session_factory() as session:
            session.add(
                AuditEvent(
                    event_type=event.event_type,
                    actor_type=event.actor_type,
                    actor_id=event.actor_id,
                    outcome=event.outcome,
                    request_id=event.request_id,
                    method=event.method,
                    path=event.path,
                    client_host=event.client_host,
                    user_agent=event.user_agent,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    metadata_json=dict(event.metadata),
                )
            )
            session.commit()
    except Exception:
        logger.warning("Could not record audit event.", exc_info=True)


def fingerprint_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def _request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else None


def _client_host(request: Request) -> str | None:
    return request.client.host if request.client is not None else None
