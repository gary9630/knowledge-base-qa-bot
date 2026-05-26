from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only, selectinload

from app.api.dependencies import get_request_db_session
from app.models.tables import Document, Section

router = APIRouter()


class SectionSummaryResponse(BaseModel):
    id: UUID
    source_id: str
    heading: str
    heading_slug: str
    level: int


class SectionResponse(SectionSummaryResponse):
    document_id: UUID
    body_md: str
    token_count: int
    content_hash: str
    created_at: str
    updated_at: str


class DocumentSummaryResponse(BaseModel):
    id: UUID
    filename: str
    title: str | None
    source_type: str
    imported_from: str | None
    section_count: int
    created_at: str
    updated_at: str


class DocumentResponse(DocumentSummaryResponse):
    canonical_path: str
    content_hash: str
    metadata: dict[str, object]
    sections: list[SectionSummaryResponse]


class SourcesResponse(BaseModel):
    documents: list[DocumentSummaryResponse]


@router.get("/sources", response_model=SourcesResponse)
def list_sources(
    session: Annotated[Session, Depends(get_request_db_session)],
) -> SourcesResponse:
    documents = session.scalars(
        select(Document)
        .options(
            load_only(
                Document.id,
                Document.filename,
                Document.title,
                Document.source_type,
                Document.imported_from,
                Document.created_at,
                Document.updated_at,
            ),
            selectinload(Document.sections).load_only(Section.id),
        )
        .where(cast(Any, Document.visibility).contains(["public"]))
        .order_by(Document.filename.asc(), Document.id.asc())
    ).all()
    return SourcesResponse(documents=[document_summary(document) for document in documents])


@router.get("/sources/{document_id}", response_model=DocumentResponse)
def get_source(
    document_id: UUID,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> DocumentResponse:
    document = session.scalar(
        select(Document)
        .options(
            selectinload(Document.sections).load_only(
                Section.id,
                Section.source_id,
                Section.heading,
                Section.heading_slug,
                Section.level,
                Section.created_at,
            )
        )
        .where(Document.id == document_id)
        .where(cast(Any, Document.visibility).contains(["public"]))
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document_response(document)


@router.get("/sources/{document_id}/sections/{section_id}", response_model=SectionResponse)
def get_source_section(
    document_id: UUID,
    section_id: UUID,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> SectionResponse:
    section = session.scalar(
        select(Section)
        .join(Document, Document.id == Section.document_id)
        .where(Section.document_id == document_id)
        .where(Section.id == section_id)
        .where(cast(Any, Document.visibility).contains(["public"]))
    )
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found.")
    return section_response(section)


def document_summary(document: Document) -> DocumentSummaryResponse:
    return DocumentSummaryResponse(
        id=document.id,
        filename=document.filename,
        title=document.title,
        source_type=document.source_type,
        imported_from=document.imported_from,
        section_count=len(document.sections),
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat(),
    )


def document_response(document: Document) -> DocumentResponse:
    sections = sorted(document.sections, key=lambda section: (section.created_at, str(section.id)))
    return DocumentResponse(
        **document_summary(document).model_dump(),
        canonical_path=document.canonical_path,
        content_hash=document.content_hash,
        metadata=dict(document.metadata_json),
        sections=[section_summary(section) for section in sections],
    )


def section_summary(section: Section) -> SectionSummaryResponse:
    return SectionSummaryResponse(
        id=section.id,
        source_id=section.source_id,
        heading=section.heading,
        heading_slug=section.heading_slug,
        level=section.level,
    )


def section_response(section: Section) -> SectionResponse:
    return SectionResponse(
        **section_summary(section).model_dump(),
        document_id=section.document_id,
        body_md=section.body_md,
        token_count=section.token_count,
        content_hash=section.content_hash,
        created_at=section.created_at.isoformat(),
        updated_at=section.updated_at.isoformat(),
    )
