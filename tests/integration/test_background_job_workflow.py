from __future__ import annotations

from collections.abc import Callable
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


def _jobs_app(db_session: Session, tmp_path: Path) -> FastAPI:
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
