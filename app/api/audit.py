from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_request_db_session, require_admin_access
from app.models.tables import AuditEvent

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_access)])


class AuditEventResponse(BaseModel):
    id: UUID
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
    metadata: dict[str, object]
    created_at: str


class AuditEventsResponse(BaseModel):
    events: list[AuditEventResponse]


@router.get("/audit-events", response_model=AuditEventsResponse)
def list_audit_events(
    session: Annotated[Session, Depends(get_request_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    event_type: str | None = None,
    outcome: str | None = None,
    actor_type: str | None = None,
) -> AuditEventsResponse:
    statement = select(AuditEvent)
    if event_type is not None:
        statement = statement.where(AuditEvent.event_type == event_type)
    if outcome is not None:
        statement = statement.where(AuditEvent.outcome == outcome)
    if actor_type is not None:
        statement = statement.where(AuditEvent.actor_type == actor_type)

    events = session.scalars(
        statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    ).all()
    return AuditEventsResponse(events=[audit_event_response(event) for event in events])


def audit_event_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
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
        metadata=dict(event.metadata_json),
        created_at=event.created_at.isoformat(),
    )
