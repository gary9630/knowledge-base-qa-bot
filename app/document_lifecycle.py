from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.tables import Chunk, Document, Section

DOCUMENT_STATUS_ACTIVE = "active"
DOCUMENT_STATUS_DISABLED = "disabled"
DOCUMENT_STATUS_DELETED = "deleted"
DOCUMENT_LIFECYCLE_STATUSES = {
    DOCUMENT_STATUS_ACTIVE,
    DOCUMENT_STATUS_DISABLED,
    DOCUMENT_STATUS_DELETED,
}
DocumentLifecycleStatus = Literal["active", "disabled", "deleted"]


def active_document_filter() -> Any:
    return Document.lifecycle_status == DOCUMENT_STATUS_ACTIVE


def purge_document_index(session: Session, document_id: UUID) -> None:
    section_ids = session.scalars(
        select(Section.id).where(Section.document_id == document_id)
    ).all()
    if not section_ids:
        return

    session.execute(delete(Chunk).where(Chunk.section_id.in_(section_ids)))
    session.execute(delete(Section).where(Section.id.in_(section_ids)))
    session.flush()


def document_section_count(session: Session, document_id: UUID) -> int:
    count = session.scalar(
        select(func.count(Section.id)).where(Section.document_id == document_id)
    )
    return int(count or 0)


def document_chunk_count(session: Session, document_id: UUID) -> int:
    count = session.scalar(
        select(func.count(Chunk.id))
        .join(Section, Section.id == Chunk.section_id)
        .where(Section.document_id == document_id)
    )
    return int(count or 0)


def normalize_lifecycle_status(value: str) -> DocumentLifecycleStatus:
    normalized = value.strip().lower()
    if normalized not in DOCUMENT_LIFECYCLE_STATUSES:
        allowed = ", ".join(sorted(DOCUMENT_LIFECYCLE_STATUSES))
        raise ValueError(
            f"Unsupported document lifecycle status: {value}. Expected one of: {allowed}."
        )
    return normalized  # type: ignore[return-value]


def dedupe_statuses(values: Iterable[str]) -> tuple[DocumentLifecycleStatus, ...]:
    statuses: list[DocumentLifecycleStatus] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_lifecycle_status(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        statuses.append(normalized)
    return tuple(statuses)
