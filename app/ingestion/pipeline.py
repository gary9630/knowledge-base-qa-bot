from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.service import import_file_to_markdown
from app.models.tables import IngestionJob


@dataclass(frozen=True)
class IngestionJobView:
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
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IngestionPipelineResult:
    job: IngestionJobView


class IngestionDestinationConflictError(Exception):
    pass


class IngestionJobNotFoundError(Exception):
    pass


class IngestionRetryNotAllowedError(Exception):
    pass


class IngestionJobStore(Protocol):
    def create_running(
        self,
        *,
        filename: str,
        content_type: str | None,
        content_hash: str,
        size_bytes: int,
        raw_path: str | None,
        canonical_path: str | None,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView: ...

    def find_succeeded_by_content_hash(self, content_hash: str) -> IngestionJobView | None: ...

    def get(self, job_id: UUID) -> IngestionJobView | None: ...

    def list_recent(self, *, limit: int) -> list[IngestionJobView]: ...

    def mark_running(self, job_id: UUID) -> IngestionJobView: ...

    def mark_duplicate(
        self,
        job_id: UUID,
        *,
        duplicate_of: IngestionJobView,
    ) -> IngestionJobView: ...

    def mark_succeeded(
        self,
        job_id: UUID,
        *,
        raw_path: str,
        canonical_path: str,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView: ...

    def mark_failed(
        self,
        job_id: UUID,
        *,
        error: str,
        raw_path: str | None = None,
        canonical_path: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView: ...


@dataclass
class _MutableIngestionJob:
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
    created_at: datetime
    updated_at: datetime

    def snapshot(self) -> IngestionJobView:
        return IngestionJobView(
            id=self.id,
            kind=self.kind,
            status=self.status,
            filename=self.filename,
            content_type=self.content_type,
            content_hash=self.content_hash,
            size_bytes=self.size_bytes,
            raw_path=self.raw_path,
            canonical_path=self.canonical_path,
            error=self.error,
            metadata=dict(self.metadata),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


@dataclass
class InMemoryIngestionJobStore:
    _jobs: dict[UUID, _MutableIngestionJob] = field(default_factory=dict)

    def create_running(
        self,
        *,
        filename: str,
        content_type: str | None,
        content_hash: str,
        size_bytes: int,
        raw_path: str | None,
        canonical_path: str | None,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView:
        now = _utc_now()
        job = _MutableIngestionJob(
            id=uuid4(),
            kind="upload",
            status="running",
            filename=filename,
            content_type=content_type,
            content_hash=content_hash,
            size_bytes=size_bytes,
            raw_path=raw_path,
            canonical_path=canonical_path,
            error=None,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.id] = job
        return job.snapshot()

    def find_succeeded_by_content_hash(self, content_hash: str) -> IngestionJobView | None:
        for job in sorted(self._jobs.values(), key=lambda item: (item.created_at, item.id)):
            if job.status == "succeeded" and job.content_hash == content_hash:
                return job.snapshot()
        return None

    def get(self, job_id: UUID) -> IngestionJobView | None:
        job = self._jobs.get(job_id)
        return job.snapshot() if job else None

    def list_recent(self, *, limit: int) -> list[IngestionJobView]:
        jobs = sorted(
            self._jobs.values(),
            key=lambda item: (item.created_at, item.id),
            reverse=True,
        )
        return [job.snapshot() for job in jobs[:limit]]

    def mark_running(self, job_id: UUID) -> IngestionJobView:
        return self._update(job_id, status="running", error=None)

    def mark_duplicate(
        self,
        job_id: UUID,
        *,
        duplicate_of: IngestionJobView,
    ) -> IngestionJobView:
        return self._update(
            job_id,
            status="duplicate",
            raw_path=duplicate_of.raw_path,
            canonical_path=duplicate_of.canonical_path,
            error=None,
            metadata={"duplicate_of": str(duplicate_of.id)},
        )

    def mark_succeeded(
        self,
        job_id: UUID,
        *,
        raw_path: str,
        canonical_path: str,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView:
        return self._update(
            job_id,
            status="succeeded",
            raw_path=raw_path,
            canonical_path=canonical_path,
            error=None,
            metadata=metadata,
        )

    def mark_failed(
        self,
        job_id: UUID,
        *,
        error: str,
        raw_path: str | None = None,
        canonical_path: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView:
        return self._update(
            job_id,
            status="failed",
            raw_path=raw_path,
            canonical_path=canonical_path,
            error=error,
            metadata=metadata,
        )

    def _update(self, job_id: UUID, **changes: object) -> IngestionJobView:
        job = self._jobs[job_id]
        for key, value in changes.items():
            if key == "metadata":
                if value is not None:
                    job.metadata.update(cast(dict[str, object], value))
                continue
            setattr(job, key, value)
        job.updated_at = _utc_now()
        return job.snapshot()


class SqlAlchemyIngestionJobStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_running(
        self,
        *,
        filename: str,
        content_type: str | None,
        content_hash: str,
        size_bytes: int,
        raw_path: str | None,
        canonical_path: str | None,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView:
        job = IngestionJob(
            kind="upload",
            status="running",
            filename=filename,
            content_type=content_type,
            content_hash=content_hash,
            size_bytes=size_bytes,
            raw_path=raw_path,
            canonical_path=canonical_path,
            metadata_json=dict(metadata or {}),
        )
        self.session.add(job)
        self._commit()
        return _job_view(job)

    def find_succeeded_by_content_hash(self, content_hash: str) -> IngestionJobView | None:
        job = self.session.scalars(
            select(IngestionJob)
            .where(
                IngestionJob.content_hash == content_hash,
                IngestionJob.status == "succeeded",
            )
            .order_by(IngestionJob.created_at.asc(), IngestionJob.id.asc())
            .limit(1)
        ).first()
        return _job_view(job) if job else None

    def get(self, job_id: UUID) -> IngestionJobView | None:
        job = self.session.get(IngestionJob, job_id)
        return _job_view(job) if job else None

    def list_recent(self, *, limit: int) -> list[IngestionJobView]:
        jobs = self.session.scalars(
            select(IngestionJob)
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
            .limit(limit)
        ).all()
        return [_job_view(job) for job in jobs]

    def mark_running(self, job_id: UUID) -> IngestionJobView:
        return self._update(job_id, status="running", error=None)

    def mark_duplicate(
        self,
        job_id: UUID,
        *,
        duplicate_of: IngestionJobView,
    ) -> IngestionJobView:
        return self._update(
            job_id,
            status="duplicate",
            raw_path=duplicate_of.raw_path,
            canonical_path=duplicate_of.canonical_path,
            error=None,
            metadata={"duplicate_of": str(duplicate_of.id)},
        )

    def mark_succeeded(
        self,
        job_id: UUID,
        *,
        raw_path: str,
        canonical_path: str,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView:
        return self._update(
            job_id,
            status="succeeded",
            raw_path=raw_path,
            canonical_path=canonical_path,
            error=None,
            metadata=metadata,
        )

    def mark_failed(
        self,
        job_id: UUID,
        *,
        error: str,
        raw_path: str | None = None,
        canonical_path: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> IngestionJobView:
        return self._update(
            job_id,
            status="failed",
            raw_path=raw_path,
            canonical_path=canonical_path,
            error=error,
            metadata=metadata,
        )

    def _update(self, job_id: UUID, **changes: object) -> IngestionJobView:
        job = self.session.get(IngestionJob, job_id)
        if job is None:
            raise KeyError(job_id)

        for key, value in changes.items():
            if key == "metadata":
                if value is not None:
                    metadata = cast(dict[str, Any], value)
                    job.metadata_json = {**job.metadata_json, **metadata}
                continue
            setattr(job, key, value)

        self._commit()
        return _job_view(job)

    def _commit(self) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise


class IngestionPipeline:
    def __init__(
        self,
        *,
        store: IngestionJobStore,
        raw_dir: Path,
        docs_dir: Path,
    ) -> None:
        self.store = store
        self.raw_dir = raw_dir
        self.docs_dir = docs_dir

    def import_upload(
        self,
        *,
        filename: str,
        content_type: str | None,
        body: bytes,
        imported_at: str | datetime | None = None,
    ) -> IngestionPipelineResult:
        content_hash = _content_hash(body)
        raw_path = self.raw_dir / filename
        canonical_path = self.docs_dir / f"{Path(filename).stem or 'document'}.md"
        job = self.store.create_running(
            filename=filename,
            content_type=content_type,
            content_hash=content_hash,
            size_bytes=len(body),
            raw_path=str(raw_path),
            canonical_path=str(canonical_path),
        )

        duplicate = self.store.find_succeeded_by_content_hash(content_hash)
        if duplicate is not None:
            return IngestionPipelineResult(
                job=self.store.mark_duplicate(job.id, duplicate_of=duplicate)
            )

        if raw_path.exists() or canonical_path.exists():
            error = "Import destination already exists."
            self.store.mark_failed(
                job.id,
                error=error,
                raw_path=str(raw_path),
                canonical_path=str(canonical_path),
            )
            raise IngestionDestinationConflictError(error)

        try:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            self.docs_dir.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(body)
            markdown = import_file_to_markdown(
                filename,
                body,
                imported_at=imported_at or _utc_now().isoformat(),
                content_hash=content_hash,
                canonical_path=_display_path(canonical_path),
            )
            canonical_path.write_text(markdown, encoding="utf-8")
        except Exception as error:
            self.store.mark_failed(
                job.id,
                error=f"{type(error).__name__}: {error}",
                raw_path=str(raw_path),
                canonical_path=str(canonical_path),
            )
            raise

        return IngestionPipelineResult(
            job=self.store.mark_succeeded(
                job.id,
                raw_path=str(raw_path),
                canonical_path=str(canonical_path),
            )
        )

    def retry_failed_job(
        self,
        *,
        job_id: UUID,
        imported_at: str | datetime | None = None,
    ) -> IngestionPipelineResult:
        job = self.store.get(job_id)
        if job is None:
            raise IngestionJobNotFoundError(f"Import job not found: {job_id}")
        if job.status != "failed":
            raise IngestionRetryNotAllowedError("Only failed import jobs can be retried.")
        if not job.raw_path or not job.canonical_path:
            raise IngestionRetryNotAllowedError("Failed import job has no raw artifact to retry.")

        raw_path = Path(job.raw_path)
        canonical_path = Path(job.canonical_path)
        try:
            body = raw_path.read_bytes()
        except OSError as error:
            self.store.mark_failed(
                job.id,
                error=f"{type(error).__name__}: {error}",
                raw_path=str(raw_path),
                canonical_path=str(canonical_path),
            )
            raise IngestionRetryNotAllowedError(
                "Raw artifact is not readable for this import job."
            ) from error

        content_hash = _content_hash(body)
        if content_hash != job.content_hash:
            raise IngestionRetryNotAllowedError("Raw artifact no longer matches failed import job.")

        self.store.mark_running(job.id)
        try:
            markdown = import_file_to_markdown(
                job.filename,
                body,
                imported_at=imported_at or _utc_now().isoformat(),
                content_hash=job.content_hash,
                canonical_path=_display_path(canonical_path),
            )
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(markdown, encoding="utf-8")
        except Exception as error:
            self.store.mark_failed(
                job.id,
                error=f"{type(error).__name__}: {error}",
                raw_path=str(raw_path),
                canonical_path=str(canonical_path),
            )
            raise

        return IngestionPipelineResult(
            job=self.store.mark_succeeded(
                job.id,
                raw_path=str(raw_path),
                canonical_path=str(canonical_path),
                metadata={"retried": True},
            )
        )


def _content_hash(body: bytes) -> str:
    return sha256(body).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _display_path(path: Path) -> str:
    return path.as_posix()


def _job_view(job: IngestionJob) -> IngestionJobView:
    return IngestionJobView(
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
        metadata=dict(job.metadata_json),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
