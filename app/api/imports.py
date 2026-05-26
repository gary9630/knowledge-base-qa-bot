from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from pypdf.errors import PdfReadError

from app.api.dependencies import (
    get_app_settings,
    get_indexing_session_factory,
    require_admin_access,
)
from app.ingestion.pipeline import (
    IngestionDestinationConflictError,
    IngestionJobNotFoundError,
    IngestionJobView,
    IngestionPipeline,
    IngestionRetryNotAllowedError,
    SqlAlchemyIngestionJobStore,
)

router = APIRouter()


class ImportJobResponse(BaseModel):
    id: UUID
    kind: str
    status: str
    filename: str
    content_type: str | None
    content_hash: str
    size_bytes: int
    raw_path: str | None
    canonical_path: str | None
    error: str | None
    metadata: dict[str, object]
    created_at: str
    updated_at: str


class ImportJobsResponse(BaseModel):
    jobs: list[ImportJobResponse]


def get_ingestion_pipeline(request: Request) -> Iterator[IngestionPipeline]:
    factory = getattr(request.app.state, "ingestion_pipeline_factory", None)
    if callable(factory):
        yield factory()
        return

    settings = get_app_settings(request)
    session_factory = get_indexing_session_factory(request)
    with session_factory() as session:
        yield IngestionPipeline(
            store=SqlAlchemyIngestionJobStore(session),
            raw_dir=Path(settings.raw_dir),
            docs_dir=Path(settings.docs_dir),
        )


def import_job_response(job: IngestionJobView) -> ImportJobResponse:
    return ImportJobResponse(
        id=job.id,
        kind=job.kind,
        status=job.status,
        filename=job.filename,
        content_type=job.content_type,
        content_hash=job.content_hash,
        size_bytes=job.size_bytes,
        raw_path=job.raw_path,
        canonical_path=job.canonical_path,
        error=job.error,
        metadata=job.metadata,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


@router.post("/imports", response_model=ImportJobResponse)
async def import_upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    pipeline: Annotated[IngestionPipeline, Depends(get_ingestion_pipeline)],
    _: Annotated[None, Depends(require_admin_access)] = None,
) -> ImportJobResponse:
    filename = _safe_filename(file.filename)

    settings = get_app_settings(request)
    body = await _read_upload_bytes(file, max_bytes=settings.max_upload_bytes)

    try:
        result = pipeline.import_upload(
            filename=filename,
            content_type=file.content_type,
            body=body,
            imported_at=datetime.now(UTC).isoformat(),
        )
    except IngestionDestinationConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, UnicodeError, PdfReadError) as error:
        raise HTTPException(
            status_code=400,
            detail=f"Could not import file: {error}",
        ) from error

    return import_job_response(result.job)


@router.get("/imports/status", response_model=ImportJobsResponse)
def import_status(
    pipeline: Annotated[IngestionPipeline, Depends(get_ingestion_pipeline)],
    _: Annotated[None, Depends(require_admin_access)] = None,
    limit: int = 20,
) -> ImportJobsResponse:
    normalized_limit = min(100, max(1, limit))
    return ImportJobsResponse(
        jobs=[
            import_job_response(job)
            for job in pipeline.store.list_recent(limit=normalized_limit)
        ]
    )


@router.get("/imports/{job_id}", response_model=ImportJobResponse)
def import_job(
    job_id: UUID,
    pipeline: Annotated[IngestionPipeline, Depends(get_ingestion_pipeline)],
    _: Annotated[None, Depends(require_admin_access)] = None,
) -> ImportJobResponse:
    job = pipeline.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found.")
    return import_job_response(job)


@router.post("/imports/{job_id}/retry", response_model=ImportJobResponse)
def retry_import_job(
    job_id: UUID,
    pipeline: Annotated[IngestionPipeline, Depends(get_ingestion_pipeline)],
    _: Annotated[None, Depends(require_admin_access)] = None,
) -> ImportJobResponse:
    try:
        result = pipeline.retry_failed_job(
            job_id=job_id,
            imported_at=datetime.now(UTC).isoformat(),
        )
    except IngestionJobNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except IngestionRetryNotAllowedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, UnicodeError, PdfReadError) as error:
        raise HTTPException(
            status_code=400,
            detail=f"Could not import file: {error}",
        ) from error

    return import_job_response(result.job)


def _safe_filename(filename: str | None) -> str:
    normalized = (filename or "").replace("\\", "/")
    name = PurePath(normalized).name
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Upload filename is required.")
    return name


async def _read_upload_bytes(file: UploadFile, *, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        raise HTTPException(status_code=500, detail="Upload limit is misconfigured.")

    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(min(1024 * 1024, max_bytes + 1))
        if not chunk:
            break

        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds configured size limit.")
        chunks.append(chunk)

    return b"".join(chunks)
