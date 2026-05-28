from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.api.dependencies import get_app_settings, get_request_db_session, require_admin_access
from app.audit import record_audit_event
from app.background_jobs.service import (
    BACKGROUND_JOB_TASK_TYPES,
    BackgroundJobInvalidTransitionError,
    BackgroundJobService,
    worker_heartbeat_is_stale,
)
from app.core.config import Settings
from app.models.tables import BackgroundJob, BackgroundWorkerHeartbeat

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_access)])
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class BackgroundJobCreateRequest(BaseModel):
    task_type: NonEmptyStr
    payload: dict[str, object] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=1000)
    max_attempts: int = Field(default=3, ge=1, le=10)


class BackgroundJobRecoverStaleRequest(BaseModel):
    stale_after_seconds: int | None = Field(default=None, ge=1)
    retry_delay_seconds: int = Field(default=0, ge=0, le=3600)
    limit: int = Field(default=100, ge=1, le=500)


class BackgroundJobRequeueRequest(BaseModel):
    reset_attempts: bool = True


class BackgroundJobResponse(BaseModel):
    id: UUID
    task_type: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    payload: dict[str, object]
    result: dict[str, object]
    error: str | None
    locked_by: str | None
    locked_at: str | None
    is_stale: bool = False
    available_at: str
    started_at: str | None
    finished_at: str | None
    created_at: str
    updated_at: str


class BackgroundJobsResponse(BaseModel):
    jobs: list[BackgroundJobResponse]


class BackgroundWorkerRuntimeWorkerResponse(BaseModel):
    worker_id: str
    status: str
    is_stale: bool
    last_seen_at: str
    started_at: str
    processed_jobs: int
    current_job_id: UUID | None
    current_task_type: str | None
    last_job_id: UUID | None
    last_task_type: str | None
    last_job_status: str | None
    last_error: str | None


class BackgroundJobsRuntimeResponse(BaseModel):
    queue: dict[str, int]
    stale_running_jobs: int
    active_workers: int
    workers: list[BackgroundWorkerRuntimeWorkerResponse]


@router.get("/jobs", response_model=BackgroundJobsResponse)
def list_background_jobs(
    session: Annotated[Session, Depends(get_request_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status: str | None = None,
) -> BackgroundJobsResponse:
    jobs = BackgroundJobService(session).list_recent(limit=limit, status=status)
    return BackgroundJobsResponse(
        jobs=[
            background_job_response(
                job,
                stale_after_seconds=settings.background_job_stale_after_seconds,
            )
            for job in jobs
        ],
    )


@router.get("/jobs/runtime", response_model=BackgroundJobsRuntimeResponse)
def get_background_jobs_runtime(
    session: Annotated[Session, Depends(get_request_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> BackgroundJobsRuntimeResponse:
    service = BackgroundJobService(session)
    checked_at = datetime.now(UTC)
    workers = service.list_worker_heartbeats()
    worker_responses = [
        background_worker_response(
            worker,
            stale_after_seconds=settings.worker_heartbeat_stale_after_seconds,
            checked_at=checked_at,
        )
        for worker in workers
    ]
    return BackgroundJobsRuntimeResponse(
        queue=service.queue_counts(),
        stale_running_jobs=service.stale_running_count(
            stale_after_seconds=settings.background_job_stale_after_seconds,
            now=checked_at,
        ),
        active_workers=sum(
            1
            for worker in worker_responses
            if not worker.is_stale and worker.status != "stopped"
        ),
        workers=worker_responses,
    )


@router.post(
    "/jobs",
    response_model=BackgroundJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_background_job(
    payload: BackgroundJobCreateRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> BackgroundJobResponse:
    if payload.task_type not in BACKGROUND_JOB_TASK_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported task_type: {payload.task_type}")

    service = BackgroundJobService(session)
    job = service.enqueue(
        task_type=payload.task_type,
        payload=payload.payload,
        priority=payload.priority,
        max_attempts=payload.max_attempts,
    )
    session.commit()
    record_audit_event(
        request,
        event_type="job.enqueued",
        actor_type="admin",
        outcome="success",
        resource_type="background_job",
        resource_id=str(job.id),
        metadata={"task_type": job.task_type},
    )
    return background_job_response(job)


@router.post("/jobs/recover-stale", response_model=BackgroundJobsResponse)
def recover_stale_background_jobs(
    payload: BackgroundJobRecoverStaleRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> BackgroundJobsResponse:
    settings = get_app_settings(request)
    stale_after_seconds = payload.stale_after_seconds or settings.background_job_stale_after_seconds
    jobs = BackgroundJobService(session).recover_stale_running_jobs(
        stale_after_seconds=stale_after_seconds,
        retry_delay_seconds=payload.retry_delay_seconds,
        limit=payload.limit,
    )
    record_audit_event(
        request,
        event_type="job.stale_recovered",
        actor_type="admin",
        outcome="success",
        resource_type="background_job",
        resource_id="background_jobs",
        metadata={"recovered_count": len(jobs)},
    )
    return BackgroundJobsResponse(
        jobs=[
            background_job_response(job, stale_after_seconds=stale_after_seconds)
            for job in jobs
        ],
    )


@router.get("/jobs/{job_id}", response_model=BackgroundJobResponse)
def get_background_job(
    job_id: UUID,
    session: Annotated[Session, Depends(get_request_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> BackgroundJobResponse:
    job = BackgroundJobService(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Background job not found.")
    return background_job_response(
        job,
        stale_after_seconds=settings.background_job_stale_after_seconds,
    )


@router.post(
    "/jobs/{job_id}/requeue",
    response_model=BackgroundJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def requeue_background_job(
    job_id: UUID,
    payload: BackgroundJobRequeueRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> BackgroundJobResponse:
    service = BackgroundJobService(session)
    try:
        job = service.requeue(job_id, reset_attempts=payload.reset_attempts)
    except BackgroundJobInvalidTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    record_audit_event(
        request,
        event_type="job.requeued",
        actor_type="admin",
        outcome="success",
        resource_type="background_job",
        resource_id=str(job.id),
        metadata={
            "task_type": job.task_type,
            "reset_attempts": payload.reset_attempts,
        },
    )
    return background_job_response(job)


@router.post("/jobs/{job_id}/cancel", response_model=BackgroundJobResponse)
def cancel_background_job(
    job_id: UUID,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> BackgroundJobResponse:
    service = BackgroundJobService(session)
    job = service.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Background job not found.")
    job = service.cancel(job.id)
    record_audit_event(
        request,
        event_type="job.canceled",
        actor_type="admin",
        outcome="success",
        resource_type="background_job",
        resource_id=str(job.id),
        metadata={"task_type": job.task_type, "status": job.status},
    )
    return background_job_response(job)


def background_job_response(
    job: BackgroundJob,
    *,
    stale_after_seconds: int | None = None,
) -> BackgroundJobResponse:
    return BackgroundJobResponse(
        id=job.id,
        task_type=job.task_type,
        status=job.status,
        priority=job.priority,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        payload=dict(job.payload_json),
        result=dict(job.result_json),
        error=job.error,
        locked_by=job.locked_by,
        locked_at=job.locked_at.isoformat() if job.locked_at else None,
        is_stale=background_job_is_stale(job, stale_after_seconds=stale_after_seconds),
        available_at=job.available_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


def background_job_is_stale(
    job: BackgroundJob,
    *,
    stale_after_seconds: int | None,
) -> bool:
    if stale_after_seconds is None or job.status != "running":
        return False
    if job.locked_at is None:
        return True
    locked_at = job.locked_at
    if locked_at.tzinfo is None:
        locked_at = locked_at.replace(tzinfo=UTC)
    stale_before = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    return locked_at <= stale_before


def background_worker_response(
    worker: BackgroundWorkerHeartbeat,
    *,
    stale_after_seconds: int,
    checked_at: datetime,
) -> BackgroundWorkerRuntimeWorkerResponse:
    return BackgroundWorkerRuntimeWorkerResponse(
        worker_id=worker.worker_id,
        status=worker.status,
        is_stale=(
            worker.status != "stopped"
            and worker_heartbeat_is_stale(
                worker,
                stale_after_seconds=stale_after_seconds,
                now=checked_at,
            )
        ),
        last_seen_at=worker.last_seen_at.isoformat(),
        started_at=worker.started_at.isoformat(),
        processed_jobs=worker.processed_jobs,
        current_job_id=worker.current_job_id,
        current_task_type=worker.current_task_type,
        last_job_id=worker.last_job_id,
        last_task_type=worker.last_task_type,
        last_job_status=worker.last_job_status,
        last_error=worker.last_error,
    )
