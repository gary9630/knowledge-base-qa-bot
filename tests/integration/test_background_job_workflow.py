from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.background_jobs.service import (
    TASK_INDEX_REBUILD,
    BackgroundJobService,
)
from app.background_jobs.worker import BackgroundWorker
from app.core.config import Settings
from app.main import create_app
from app.models.tables import AuditEvent, BackgroundJob, Document
from app.retrieval.embeddings import FakeEmbeddingProvider


def test_admin_can_queue_index_job_and_worker_completes_it(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path)
    client = TestClient(app)
    admin_headers = {"X-KB-Admin-Key": "secret"}

    queue_response = client.post(
        "/admin/jobs",
        headers=admin_headers,
        json={"task_type": TASK_INDEX_REBUILD, "payload": {"reason": "manual"}},
    )
    job_id = UUID(queue_response.json()["id"])
    processed = _worker(app, db_session).run_once()
    status_response = client.get(f"/admin/jobs/{job_id}", headers=admin_headers)

    assert queue_response.status_code == 202
    assert queue_response.json()["status"] == "queued"
    assert queue_response.json()["payload"] == {"reason": "manual"}
    assert processed is not None
    assert processed.id == job_id

    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "succeeded"
    assert status_body["task_type"] == TASK_INDEX_REBUILD
    assert status_body["attempts"] == 1
    assert status_body["locked_by"] is None
    assert status_body["result"]["files_indexed"] == 1
    assert status_body["result"]["sections_indexed"] == 1
    assert status_body["result"]["chunks_indexed"] >= 1

    document = db_session.scalar(select(Document).where(Document.filename == "course.md"))
    assert document is not None
    assert document.lifecycle_status == "active"

    audit_event = db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.event_type == "job.enqueued")
        .where(AuditEvent.resource_id == str(job_id))
    )
    assert audit_event is not None
    assert audit_event.metadata_json["task_type"] == TASK_INDEX_REBUILD


def test_background_worker_retries_failed_jobs_until_max_attempts(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path)
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type="unknown.task", max_attempts=2)
    db_session.commit()
    worker = _worker(app, db_session)

    first_processed = worker.run_once()
    db_session.expire_all()
    first_state = db_session.get(BackgroundJob, job.id)
    assert first_state is not None
    first_status = first_state.status
    first_attempts = first_state.attempts
    first_error = first_state.error
    second_processed = worker.run_once()
    db_session.expire_all()
    final_state = db_session.get(BackgroundJob, job.id)

    assert first_processed is not None
    assert first_processed.id == job.id
    assert first_status == "queued"
    assert first_attempts == 1
    assert "unsupported background job task" in (first_error or "")
    assert second_processed is not None
    assert final_state is not None
    assert final_state.status == "failed"
    assert final_state.attempts == 2
    assert final_state.finished_at is not None
    assert final_state.locked_by is None


def test_background_worker_applies_retry_backoff(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path, retry_base_delay_seconds=10)
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type="unknown.task", max_attempts=3)
    db_session.commit()
    worker = _worker(app, db_session)
    before = datetime.now(UTC)

    first_processed = worker.run_once()
    db_session.expire_all()
    first_state = db_session.get(BackgroundJob, job.id)
    second_processed = worker.run_once()

    assert first_processed is not None
    assert first_state is not None
    assert first_state.status == "queued"
    assert first_state.attempts == 1
    assert first_state.available_at >= before + timedelta(seconds=9)
    assert second_processed is None


def test_stale_running_job_is_requeued_for_new_worker(
    db_session: Session,
    tmp_path: Path,
) -> None:
    _jobs_app(db_session, tmp_path)
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type=TASK_INDEX_REBUILD, max_attempts=3)
    db_session.commit()
    now = job.available_at + timedelta(seconds=1)
    claimed = service.claim_next(worker_id="dead-worker", now=now)
    assert claimed is not None

    recovered = service.recover_stale_running_jobs(
        stale_after_seconds=60,
        retry_delay_seconds=0,
        now=now + timedelta(seconds=61),
    )

    assert [item.id for item in recovered] == [job.id]
    assert recovered[0].status == "queued"
    assert recovered[0].locked_by is None
    assert recovered[0].locked_at is None
    assert recovered[0].attempts == 1
    assert "Recovered stale running job" in (recovered[0].error or "")

    next_claim = service.claim_next(
        worker_id="new-worker",
        now=now + timedelta(seconds=62),
    )

    assert next_claim is not None
    assert next_claim.id == job.id
    assert next_claim.status == "running"
    assert next_claim.locked_by == "new-worker"
    assert next_claim.attempts == 2


def test_stale_running_job_fails_when_attempts_are_exhausted(
    db_session: Session,
    tmp_path: Path,
) -> None:
    _jobs_app(db_session, tmp_path)
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type=TASK_INDEX_REBUILD, max_attempts=1)
    db_session.commit()
    now = job.available_at + timedelta(seconds=1)
    claimed = service.claim_next(worker_id="dead-worker", now=now)
    assert claimed is not None

    recovered = service.recover_stale_running_jobs(
        stale_after_seconds=60,
        retry_delay_seconds=0,
        now=now + timedelta(seconds=61),
    )

    assert [item.id for item in recovered] == [job.id]
    assert recovered[0].status == "failed"
    assert recovered[0].locked_by is None
    assert recovered[0].finished_at is not None
    assert "Recovered stale running job" in (recovered[0].error or "")


def test_worker_recovers_stale_job_before_claiming(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path, stale_after_seconds=60)
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type=TASK_INDEX_REBUILD, max_attempts=3)
    db_session.commit()
    claimed = service.claim_next(
        worker_id="dead-worker",
        now=job.available_at + timedelta(seconds=1),
    )
    assert claimed is not None
    claimed.locked_at = datetime.now(UTC) - timedelta(seconds=120)
    db_session.commit()
    worker = _worker(app, db_session)

    processed = worker.run_once()
    db_session.expire_all()
    final_state = db_session.get(BackgroundJob, job.id)

    assert processed is not None
    assert processed.id == job.id
    assert final_state is not None
    assert final_state.status == "succeeded"
    assert final_state.attempts == 2
    assert final_state.locked_by is None


def test_admin_can_recover_stale_jobs(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path)
    client = TestClient(app)
    admin_headers = {"X-KB-Admin-Key": "secret"}
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type=TASK_INDEX_REBUILD, max_attempts=3)
    db_session.commit()
    claimed = service.claim_next(
        worker_id="dead-worker",
        now=job.available_at + timedelta(seconds=1),
    )
    assert claimed is not None
    claimed.locked_at = datetime.now(UTC) - timedelta(seconds=120)
    db_session.commit()

    response = client.post(
        "/admin/jobs/recover-stale",
        headers=admin_headers,
        json={"stale_after_seconds": 60, "retry_delay_seconds": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["jobs"]] == [str(job.id)]
    assert body["jobs"][0]["status"] == "queued"

    audit_event = db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.event_type == "job.stale_recovered")
        .where(AuditEvent.resource_id == "background_jobs")
    )
    assert audit_event is not None
    assert audit_event.metadata_json["recovered_count"] == 1


def test_admin_jobs_api_marks_stale_running_jobs_from_settings(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path, stale_after_seconds=60)
    client = TestClient(app)
    admin_headers = {"X-KB-Admin-Key": "secret"}
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type=TASK_INDEX_REBUILD, max_attempts=3)
    db_session.commit()
    claimed = service.claim_next(
        worker_id="dead-worker",
        now=job.available_at + timedelta(seconds=1),
    )
    assert claimed is not None
    claimed.locked_at = datetime.now(UTC) - timedelta(seconds=120)
    db_session.commit()

    list_response = client.get("/admin/jobs", headers=admin_headers)
    detail_response = client.get(f"/admin/jobs/{job.id}", headers=admin_headers)

    assert list_response.status_code == 200
    assert list_response.json()["jobs"][0]["is_stale"] is True
    assert detail_response.status_code == 200
    assert detail_response.json()["is_stale"] is True


def test_admin_can_requeue_failed_job(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path)
    client = TestClient(app)
    admin_headers = {"X-KB-Admin-Key": "secret"}
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type="unknown.task", max_attempts=1)
    db_session.commit()
    failed_job = _worker(app, db_session).run_once()
    assert failed_job is not None
    assert failed_job.status == "failed"

    response = client.post(
        f"/admin/jobs/{job.id}/requeue",
        headers=admin_headers,
        json={"reset_attempts": True},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["attempts"] == 0
    assert body["locked_by"] is None
    assert body["error"] is None

    audit_event = db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.event_type == "job.requeued")
        .where(AuditEvent.resource_id == str(job.id))
    )
    assert audit_event is not None


def test_admin_jobs_api_requires_admin_key(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_jobs_app(db_session, tmp_path))

    unauthenticated = client.get("/admin/jobs")
    authenticated = client.get("/admin/jobs", headers={"X-KB-Admin-Key": "secret"})

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json() == {"jobs": []}


def _jobs_app(
    db_session: Session,
    tmp_path: Path,
    *,
    retry_base_delay_seconds: int = 0,
    stale_after_seconds: int = 3600,
) -> FastAPI:
    docs_dir = tmp_path / "docs"
    raw_dir = tmp_path / "raw"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "course.md").write_text(
        "# Course Guide\n\nThe course website is https://example.test/.\n",
        encoding="utf-8",
    )
    settings = Settings(
        docs_dir=str(docs_dir),
        raw_dir=str(raw_dir),
        kb_dir=str(kb_dir),
        embedding_provider="fake",
        answer_provider="fake",
        admin_api_key="secret",
        background_job_retry_base_delay_seconds=retry_base_delay_seconds,
        background_job_stale_after_seconds=stale_after_seconds,
    )
    return create_app(settings=settings, session_factory=_session_factory(db_session))


def _worker(app: FastAPI, db_session: Session) -> BackgroundWorker:
    return BackgroundWorker(
        session_factory=_session_factory(db_session),
        settings=app.state.settings,
        embedding_provider=FakeEmbeddingProvider(),
        answer_provider=app.state.answer_provider,
        worker_id="test-worker",
    )


def _session_factory(db_session: Session) -> Callable[[], Session]:
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return create_session
