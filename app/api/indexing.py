from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_app_settings,
    get_embedding_provider,
    get_indexing_session_factory,
    get_request_db_session,
    require_admin_access,
)
from app.indexing.service import IndexingService
from app.models.tables import Chunk, IndexingJob

router = APIRouter()


class ReadyResponse(BaseModel):
    database: bool
    index: bool
    ready: bool


class IndexRebuildResponse(BaseModel):
    status: str
    files_indexed: int
    sections_indexed: int
    chunks_indexed: int
    export_path: str


class IndexingJobResponse(BaseModel):
    id: UUID
    kind: str
    status: str
    input_path: str | None
    error: str | None
    stats: dict[str, Any]
    created_at: str
    updated_at: str


@router.get("/ready", response_model=ReadyResponse)
def ready(session: Annotated[Session, Depends(get_request_db_session)]) -> ReadyResponse:
    session.execute(select(1)).scalar_one()
    index_ready = index_is_ready(session)
    return ReadyResponse(database=True, index=index_ready, ready=index_ready)


@router.post("/index", response_model=IndexRebuildResponse)
def rebuild_index(
    request: Request,
    _: Annotated[None, Depends(require_admin_access)] = None,
) -> IndexRebuildResponse:
    settings = get_app_settings(request)
    session_factory = get_indexing_session_factory(request)
    with session_factory() as session:
        try:
            result = IndexingService(
                session=session,
                docs_dir=Path(settings.docs_dir),
                kb_dir=Path(settings.kb_dir),
                embedding_provider=get_embedding_provider(request),
            ).rebuild_index()
        except (FileNotFoundError, NotADirectoryError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Index rebuild failed: {error}",
            ) from error

    return IndexRebuildResponse(
        status="succeeded",
        files_indexed=result.files_indexed,
        sections_indexed=result.sections_indexed,
        chunks_indexed=result.chunks_indexed,
        export_path=str(result.export_path),
    )


@router.get("/index/status", response_model=IndexingJobResponse)
def index_status(
    session: Annotated[Session, Depends(get_request_db_session)],
) -> IndexingJobResponse:
    job = latest_indexing_job(session)
    if job is None:
        raise HTTPException(status_code=404, detail="No indexing job has run.")
    return indexing_job_response(job)


def latest_indexing_job(session: Session) -> IndexingJob | None:
    return session.scalars(
        select(IndexingJob).order_by(IndexingJob.created_at.desc(), IndexingJob.id.desc()).limit(1)
    ).first()


def index_is_ready(session: Session) -> bool:
    latest_job = latest_indexing_job(session)
    if latest_job is None or latest_job.status != "succeeded":
        return False

    chunk_count = session.scalar(select(func.count(Chunk.id)))
    return int(chunk_count or 0) > 0


def indexing_job_response(job: IndexingJob) -> IndexingJobResponse:
    return IndexingJobResponse(
        id=job.id,
        kind=job.kind,
        status=job.status,
        input_path=job.input_path,
        error=job.error,
        stats=dict(job.stats_json),
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )
