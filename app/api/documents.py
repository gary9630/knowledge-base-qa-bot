from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_app_settings,
    get_embedding_provider,
    get_indexing_session_factory,
    get_request_db_session,
    require_admin_access,
)
from app.audit import record_audit_event
from app.document_lifecycle import (
    DOCUMENT_STATUS_ACTIVE,
    DOCUMENT_STATUS_DELETED,
    DOCUMENT_STATUS_DISABLED,
    document_chunk_count,
    document_section_count,
    normalize_lifecycle_status,
    purge_document_index,
)
from app.indexing.service import DocumentNotFoundError, IndexingService
from app.models.tables import Document

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_access)])


class AdminDocumentResponse(BaseModel):
    id: UUID
    filename: str
    title: str | None
    source_type: str
    imported_from: str | None
    canonical_path: str
    canonical_exists: bool
    content_hash: str
    visibility: list[str]
    lifecycle_status: str
    lifecycle_reason: str | None
    index_status: str
    section_count: int
    chunk_count: int
    metadata: dict[str, object]
    created_at: str
    updated_at: str


class AdminDocumentsResponse(BaseModel):
    documents: list[AdminDocumentResponse]


class DocumentLifecycleRequest(BaseModel):
    status: Literal["active", "disabled"]
    reason: str | None = Field(default=None, max_length=500)


@router.get("/documents", response_model=AdminDocumentsResponse)
def list_admin_documents(
    session: Annotated[Session, Depends(get_request_db_session)],
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AdminDocumentsResponse:
    statement = select(Document)
    if status is not None:
        try:
            statement = statement.where(
                Document.lifecycle_status == normalize_lifecycle_status(status)
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    documents = session.scalars(
        statement.order_by(Document.filename.asc(), Document.id.asc()).limit(limit)
    ).all()
    return AdminDocumentsResponse(
        documents=[
            admin_document_response(session, document)
            for document in documents
        ]
    )


@router.patch("/documents/{document_id}/lifecycle", response_model=AdminDocumentResponse)
def update_document_lifecycle(
    document_id: UUID,
    payload: DocumentLifecycleRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> AdminDocumentResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    document.lifecycle_status = payload.status
    document.lifecycle_reason = (
        payload.reason if payload.status == DOCUMENT_STATUS_DISABLED else None
    )
    session.commit()

    event_type = (
        "document.enabled"
        if payload.status == DOCUMENT_STATUS_ACTIVE
        else "document.disabled"
    )
    record_audit_event(
        request,
        event_type=event_type,
        actor_type="admin",
        outcome="success",
        resource_type="document",
        resource_id=str(document.id),
        metadata={
            "filename": document.filename,
            "lifecycle_status": document.lifecycle_status,
            "reason": document.lifecycle_reason,
        },
    )
    return admin_document_response(session, document)


@router.delete("/documents/{document_id}", response_model=AdminDocumentResponse)
def delete_document_from_index(
    document_id: UUID,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> AdminDocumentResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    purge_document_index(session, document.id)
    document.lifecycle_status = DOCUMENT_STATUS_DELETED
    document.lifecycle_reason = "deleted_from_index"
    session.commit()

    record_audit_event(
        request,
        event_type="document.deleted",
        actor_type="admin",
        outcome="success",
        resource_type="document",
        resource_id=str(document.id),
        metadata={
            "filename": document.filename,
            "canonical_path": document.canonical_path,
            "source_file_deleted": False,
        },
    )
    return admin_document_response(session, document)


@router.post("/documents/{document_id}/reindex", response_model=AdminDocumentResponse)
def reindex_document(
    document_id: UUID,
    request: Request,
) -> AdminDocumentResponse:
    settings = get_app_settings(request)
    session_factory = get_indexing_session_factory(request)
    with session_factory() as session:
        try:
            result = IndexingService(
                session=session,
                docs_dir=Path(settings.docs_dir),
                kb_dir=Path(settings.kb_dir),
                embedding_provider=get_embedding_provider(request),
            ).reindex_document(document_id)
        except DocumentNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Document reindex failed: {error}",
            ) from error

        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        response = admin_document_response(session, document)

    record_audit_event(
        request,
        event_type="document.reindexed",
        actor_type="admin",
        outcome="success",
        resource_type="document",
        resource_id=str(document_id),
        metadata={
            "files_indexed": result.files_indexed,
            "sections_indexed": result.sections_indexed,
            "chunks_indexed": result.chunks_indexed,
        },
    )
    return response


def admin_document_response(
    session: Session,
    document: Document,
) -> AdminDocumentResponse:
    canonical_exists = Path(document.canonical_path).exists()
    section_count = document_section_count(session, document.id)
    chunk_count = document_chunk_count(session, document.id)
    return AdminDocumentResponse(
        id=document.id,
        filename=document.filename,
        title=document.title,
        source_type=document.source_type,
        imported_from=document.imported_from,
        canonical_path=document.canonical_path,
        canonical_exists=canonical_exists,
        content_hash=document.content_hash,
        visibility=list(document.visibility),
        lifecycle_status=document.lifecycle_status,
        lifecycle_reason=document.lifecycle_reason,
        index_status=_index_status(
            document,
            canonical_exists=canonical_exists,
            section_count=section_count,
            chunk_count=chunk_count,
        ),
        section_count=section_count,
        chunk_count=chunk_count,
        metadata=dict(document.metadata_json),
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat(),
    )


def _index_status(
    document: Document,
    *,
    canonical_exists: bool,
    section_count: int,
    chunk_count: int,
) -> str:
    if document.lifecycle_status == DOCUMENT_STATUS_DELETED:
        return DOCUMENT_STATUS_DELETED
    if document.lifecycle_status == DOCUMENT_STATUS_DISABLED:
        return DOCUMENT_STATUS_DISABLED
    if not canonical_exists:
        return "source_missing"
    if section_count <= 0 or chunk_count <= 0:
        return "not_indexed"
    return "indexed"
