from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.tables import BackgroundJob

TASK_INGEST_UPLOAD = "ingest.upload"
TASK_INDEX_REBUILD = "index.rebuild"
TASK_DOCUMENT_REINDEX = "document.reindex"
TASK_EVAL_RUN = "eval.run"
BACKGROUND_JOB_TASK_TYPES = {
    TASK_INGEST_UPLOAD,
    TASK_INDEX_REBUILD,
    TASK_DOCUMENT_REINDEX,
    TASK_EVAL_RUN,
}

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"


class BackgroundJobNotFoundError(ValueError):
    pass


class BackgroundJobInvalidTransitionError(ValueError):
    pass


class BackgroundJobService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        *,
        task_type: str,
        payload: dict[str, object] | None = None,
        priority: int = 100,
        max_attempts: int = 3,
        available_at: datetime | None = None,
    ) -> BackgroundJob:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        job = BackgroundJob(
            task_type=task_type,
            status=STATUS_QUEUED,
            priority=priority,
            attempts=0,
            max_attempts=max_attempts,
            payload_json=dict(payload or {}),
            result_json={},
            available_at=available_at or _utcnow(),
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get(self, job_id: UUID) -> BackgroundJob | None:
        return self.session.get(BackgroundJob, job_id)

    def require(self, job_id: UUID) -> BackgroundJob:
        job = self.get(job_id)
        if job is None:
            raise BackgroundJobNotFoundError(f"Background job not found: {job_id}")
        return job

    def list_recent(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
    ) -> list[BackgroundJob]:
        statement = select(BackgroundJob)
        if status is not None:
            statement = statement.where(BackgroundJob.status == status)
        statement = statement.order_by(
            BackgroundJob.created_at.desc(),
            BackgroundJob.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement).all())

    def claim_next(
        self,
        *,
        worker_id: str,
        task_types: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> BackgroundJob | None:
        claimed_at = now or _utcnow()
        statement = (
            select(BackgroundJob)
            .where(BackgroundJob.status == STATUS_QUEUED)
            .where(BackgroundJob.available_at <= claimed_at)
            .order_by(
                BackgroundJob.priority.asc(),
                BackgroundJob.created_at.asc(),
                BackgroundJob.id.asc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if task_types is not None:
            normalized_task_types = tuple(task_types)
            if not normalized_task_types:
                return None
            statement = statement.where(BackgroundJob.task_type.in_(normalized_task_types))

        job = self.session.scalars(statement).first()
        if job is None:
            return None

        job.status = STATUS_RUNNING
        job.attempts += 1
        job.locked_by = worker_id
        job.locked_at = claimed_at
        job.started_at = job.started_at or claimed_at
        job.finished_at = None
        job.error = None
        self.session.commit()
        return job

    def complete(self, job_id: UUID, *, result: dict[str, object] | None = None) -> BackgroundJob:
        job = self.require(job_id)
        job.status = STATUS_SUCCEEDED
        job.result_json = dict(result or {})
        job.error = None
        job.locked_by = None
        job.locked_at = None
        job.finished_at = _utcnow()
        self.session.commit()
        return job

    def fail(
        self,
        job_id: UUID,
        *,
        error: str,
        retry_delay_seconds: int = 0,
    ) -> BackgroundJob:
        job = self.require(job_id)
        now = _utcnow()
        job.error = error
        job.locked_by = None
        job.locked_at = None
        if job.attempts < job.max_attempts:
            job.status = STATUS_QUEUED
            job.available_at = now + timedelta(seconds=max(0, retry_delay_seconds))
            job.finished_at = None
        else:
            job.status = STATUS_FAILED
            job.finished_at = now
        self.session.commit()
        return job

    def recover_stale_running_jobs(
        self,
        *,
        stale_after_seconds: int,
        retry_delay_seconds: int = 0,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[BackgroundJob]:
        if stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be at least 1")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        recovered_at = now or _utcnow()
        stale_before = recovered_at - timedelta(seconds=stale_after_seconds)
        jobs = self.session.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.status == STATUS_RUNNING)
            .where(
                or_(
                    BackgroundJob.locked_at.is_(None),
                    BackgroundJob.locked_at <= stale_before,
                )
            )
            .order_by(BackgroundJob.locked_at.asc().nullsfirst(), BackgroundJob.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()

        recovered: list[BackgroundJob] = []
        for job in jobs:
            previous_worker = job.locked_by or "unknown worker"
            job.error = f"Recovered stale running job locked by {previous_worker}."
            job.locked_by = None
            job.locked_at = None
            if job.attempts < job.max_attempts:
                job.status = STATUS_QUEUED
                job.available_at = recovered_at + timedelta(seconds=retry_delay_seconds)
                job.finished_at = None
            else:
                job.status = STATUS_FAILED
                job.finished_at = recovered_at
            recovered.append(job)

        if recovered:
            self.session.commit()
        return recovered

    def requeue(
        self,
        job_id: UUID,
        *,
        reset_attempts: bool = True,
        now: datetime | None = None,
    ) -> BackgroundJob:
        job = self.require(job_id)
        if job.status not in {STATUS_FAILED, STATUS_CANCELED}:
            raise BackgroundJobInvalidTransitionError(
                "Only failed or canceled background jobs can be requeued."
            )

        job.status = STATUS_QUEUED
        if reset_attempts:
            job.attempts = 0
        job.error = None
        job.locked_by = None
        job.locked_at = None
        job.available_at = now or _utcnow()
        job.finished_at = None
        self.session.commit()
        return job

    def cancel(self, job_id: UUID) -> BackgroundJob:
        job = self.require(job_id)
        if job.status == STATUS_QUEUED:
            job.status = STATUS_CANCELED
            job.locked_by = None
            job.locked_at = None
            job.finished_at = _utcnow()
            self.session.commit()
        return job


def _utcnow() -> datetime:
    return datetime.now(UTC)
