from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_app_settings,
    get_embedding_provider,
    get_indexing_session_factory,
    get_request_db_session,
    require_admin_access,
)
from app.auth.sessions import platform_auth_is_configured, platform_auth_requires_configuration
from app.core.config import Settings
from app.indexing.service import IndexingService
from app.models.tables import Chunk, IndexingJob

router = APIRouter()


class ReadyCheck(BaseModel):
    ok: bool
    detail: str | None = None
    current_revision: str | None = None
    head_revision: str | None = None


class ReadyResponse(BaseModel):
    database: bool
    index: bool
    ready: bool
    checks: dict[str, ReadyCheck]


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


@router.get("/ready", response_model=ReadyResponse, response_model_exclude_none=True)
def ready(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> ReadyResponse:
    settings = get_app_settings(request)
    checks = readiness_checks(session, settings=settings)
    index_ready = checks["index"].ok
    database_ready = checks["database"].ok
    ready_value = all(check.ok for check in checks.values())
    if not ready_value:
        response.status_code = 503
    return ReadyResponse(
        database=database_ready,
        index=index_ready,
        ready=ready_value,
        checks=checks,
    )


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


def readiness_checks(session: Session, *, settings: Settings) -> dict[str, ReadyCheck]:
    checks: dict[str, ReadyCheck] = {}
    try:
        session.execute(select(1)).scalar_one()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Database readiness check failed: {error.__class__.__name__}",
        ) from error

    checks["database"] = ReadyCheck(ok=True)
    checks["pgvector"] = pgvector_ready_check(session)
    checks["migrations"] = migration_ready_check(session)
    checks["index"] = index_ready_check(session)
    checks["platform_auth"] = platform_auth_ready_check(settings)
    return checks


def pgvector_ready_check(session: Session) -> ReadyCheck:
    try:
        version = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
    except SQLAlchemyError as error:
        rollback_readiness_session(session)
        return readiness_check_failed("pgvector", error)

    if version is None:
        return ReadyCheck(ok=False, detail="pgvector extension is not installed.")
    return ReadyCheck(ok=True, detail=str(version))


def migration_ready_check(session: Session) -> ReadyCheck:
    try:
        current_revision = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        head_revision = alembic_head_revision()
    except SQLAlchemyError as error:
        rollback_readiness_session(session)
        return readiness_check_failed("Migration", error)
    except RuntimeError as error:
        return readiness_check_failed("Migration", error)

    return ReadyCheck(
        ok=current_revision == head_revision,
        current_revision=str(current_revision),
        head_revision=head_revision,
        detail=None if current_revision == head_revision else "Database migration is not at head.",
    )


def alembic_head_revision() -> str:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Alembic head revision is not configured.")
    return head


def index_ready_check(session: Session) -> ReadyCheck:
    try:
        if index_is_ready(session):
            return ReadyCheck(ok=True)
    except SQLAlchemyError as error:
        rollback_readiness_session(session)
        return readiness_check_failed("Index", error)

    return ReadyCheck(ok=False, detail="No successful index with chunks is available.")


def platform_auth_ready_check(settings: Settings) -> ReadyCheck:
    if platform_auth_is_configured(settings):
        return ReadyCheck(ok=True)
    if platform_auth_requires_configuration(settings):
        return ReadyCheck(
            ok=False,
            detail="Platform auth is required but not configured.",
        )
    return ReadyCheck(ok=True, detail="Platform auth is not configured in development.")


def readiness_check_failed(name: str, error: Exception) -> ReadyCheck:
    return ReadyCheck(ok=False, detail=f"{name} readiness check failed: {error.__class__.__name__}")


def rollback_readiness_session(session: Session) -> None:
    try:
        session.rollback()
    except SQLAlchemyError:
        pass


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
