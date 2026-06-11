from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.background_jobs.service import (
    TASK_CONCEPT_EXTRACTION,
    TASK_INDEX_REBUILD,
    BackgroundJobService,
)
from app.background_jobs.worker import BackgroundWorker
from app.core.config import Settings
from app.graph.extraction import ChatCaller
from app.main import create_app
from app.models.tables import (
    AuditEvent,
    BackgroundJob,
    Concept,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)
from app.provider_telemetry import ProviderCallRecord, ProviderUsage
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


def test_admin_jobs_runtime_reports_queue_and_worker_heartbeat(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path, worker_heartbeat_stale_after_seconds=60)
    client = TestClient(app)
    admin_headers = {"X-KB-Admin-Key": "secret"}
    service = BackgroundJobService(db_session)
    service.enqueue(task_type=TASK_INDEX_REBUILD)
    service.record_worker_heartbeat(worker_id="worker-a", status="idle")
    db_session.commit()

    response = client.get("/admin/jobs/runtime", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["queue"]["queued"] == 1
    assert body["queue"]["running"] == 0
    assert body["stale_running_jobs"] == 0
    assert body["active_workers"] == 1
    assert body["workers"][0]["worker_id"] == "worker-a"
    assert body["workers"][0]["status"] == "idle"
    assert body["workers"][0]["is_stale"] is False


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


def test_index_rebuild_chains_concept_extraction_when_enabled(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path, graph_extraction_enabled=True)
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type=TASK_INDEX_REBUILD, payload={"reason": "manual"})
    db_session.commit()
    worker = _worker(app, db_session)

    processed = worker.run_once()
    db_session.expire_all()

    assert processed is not None
    assert processed.id == job.id
    assert processed.status == "succeeded"

    concept_extraction_jobs = db_session.scalars(
        select(BackgroundJob).where(BackgroundJob.task_type == TASK_CONCEPT_EXTRACTION)
    ).all()
    assert len(concept_extraction_jobs) == 1
    assert concept_extraction_jobs[0].status == "queued"
    assert concept_extraction_jobs[0].payload_json["reason"] == TASK_INDEX_REBUILD


def test_index_rebuild_does_not_chain_concept_extraction_when_disabled(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path, graph_extraction_enabled=False)
    service = BackgroundJobService(db_session)
    service.enqueue(task_type=TASK_INDEX_REBUILD, payload={"reason": "manual"})
    db_session.commit()
    worker = _worker(app, db_session)

    processed = worker.run_once()
    db_session.expire_all()

    assert processed is not None
    assert processed.status == "succeeded"

    concept_extraction_jobs = db_session.scalars(
        select(BackgroundJob).where(BackgroundJob.task_type == TASK_CONCEPT_EXTRACTION)
    ).all()
    assert concept_extraction_jobs == []


def test_concept_extraction_without_openai_caller_skips_and_leaves_graph_untouched(
    db_session: Session,
    tmp_path: Path,
) -> None:
    # Default providers (answer_provider="fake") must NOT run the extraction
    # pipeline: an empty extraction would wipe concept_sources and seal the
    # extraction state at the current hash, hiding the pending document from
    # a later real extraction.
    app = _jobs_app(db_session, tmp_path)
    document = _seed_graph_document(db_session, filename="pending.md", content_hash="hash-v2")
    section = db_session.scalars(
        select(Section).where(Section.document_id == document.id)
    ).one()
    concept = Concept(name="Caching", slug="caching", summary="既有概念。")
    db_session.add(concept)
    db_session.flush()
    db_session.add(ConceptSource(concept_id=concept.id, section_id=section.id))
    db_session.add(ConceptExtractionState(document_id=document.id, content_hash="hash-v1"))
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type=TASK_CONCEPT_EXTRACTION, payload={"reason": "manual"})
    db_session.commit()

    processed = _worker(app, db_session).run_once()
    db_session.expire_all()

    assert processed is not None
    assert processed.id == job.id
    assert processed.status == "succeeded"
    final_state = db_session.get(BackgroundJob, job.id)
    assert final_state is not None
    assert final_state.result_json == {
        "skipped": True,
        "reason": "graph extraction requires answer_provider=openai",
    }

    sources = db_session.scalars(select(ConceptSource)).all()
    assert len(sources) == 1
    assert sources[0].concept_id == concept.id
    assert sources[0].section_id == section.id
    extraction_state = db_session.scalar(select(ConceptExtractionState))
    assert extraction_state is not None
    assert extraction_state.content_hash == "hash-v1"  # still pending, not sealed
    assert db_session.scalar(select(Concept).where(Concept.slug == "caching")) is not None


def test_concept_extraction_job_runs_pipeline_with_injected_caller(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _jobs_app(db_session, tmp_path)
    document = _seed_graph_document(db_session, filename="pending.md", content_hash="hash-v1")
    service = BackgroundJobService(db_session)
    job = service.enqueue(task_type=TASK_CONCEPT_EXTRACTION, payload={"reason": "manual"})
    db_session.commit()
    caller = _RecordingGraphCaller(
        {
            # no merge response: with no pre-existing concepts the merge call is skipped
            "extract a concept graph": json.dumps(
                {
                    "concepts": [
                        {
                            "name": "Caching",
                            "summary": "快取摘要。",
                            "source_ids": [f"{document.filename}#s1"],
                        }
                    ],
                    "edges": [],
                }
            ),
            "assign the given course concepts": json.dumps(
                {"clusters": [{"name": "快取", "concepts": ["Caching"]}]}
            ),
            "Propose edges": json.dumps({"edges": []}),
        }
    )

    processed = _worker(app, db_session, graph_caller=caller).run_once()
    db_session.expire_all()

    assert processed is not None
    assert processed.id == job.id
    assert processed.status == "succeeded"

    concepts = db_session.scalars(select(Concept)).all()
    assert [concept.name for concept in concepts] == ["Caching"]

    final_state = db_session.get(BackgroundJob, job.id)
    assert final_state is not None
    result = final_state.result_json
    assert result["documents_extracted"] == 1
    # extract -> cluster -> cluster-edges, telemetry surfaced from call_records
    assert result["provider_calls"] == 3
    assert result["provider_tokens"] == 30
    assert result["provider_failures"] == 0


class _RecordingGraphCaller:
    """Scripted ChatCaller keyed by system-prompt marker, exposing call_records."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses
        self.call_records: list[ProviderCallRecord] = []

    def complete(self, *, system: str, user: str) -> str:  # noqa: ARG002
        self.call_records.append(
            ProviderCallRecord(
                provider="stub",
                operation="graph_extraction",
                model="stub-model",
                status="succeeded",
                usage=ProviderUsage(total_tokens=10),
                usage_complete=True,
            )
        )
        for marker, response in self._responses.items():
            if marker in system:
                return response
        raise AssertionError(f"unexpected graph extraction call: {system[:80]!r}")


def _seed_graph_document(
    db_session: Session,
    *,
    filename: str,
    content_hash: str,
) -> Document:
    document = Document(
        filename=filename,
        canonical_path=f"/docs/{filename}",
        source_type="markdown",
        content_hash=content_hash,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        Section(
            document_id=document.id,
            source_id=f"{filename}#s1",
            heading="s1",
            heading_slug="s1",
            level=2,
            body_md="s1 的內容。",
            token_count=8,
            content_hash=f"{filename}-s1",
            position=0,
        )
    )
    db_session.flush()
    return document


def _jobs_app(
    db_session: Session,
    tmp_path: Path,
    *,
    retry_base_delay_seconds: int = 0,
    stale_after_seconds: int = 3600,
    worker_heartbeat_stale_after_seconds: int = 120,
    graph_extraction_enabled: bool = True,
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
        worker_heartbeat_stale_after_seconds=worker_heartbeat_stale_after_seconds,
        graph_extraction_enabled=graph_extraction_enabled,
    )
    return create_app(settings=settings, session_factory=_session_factory(db_session))


def _worker(
    app: FastAPI,
    db_session: Session,
    *,
    graph_caller: ChatCaller | None = None,
) -> BackgroundWorker:
    return BackgroundWorker(
        session_factory=_session_factory(db_session),
        settings=app.state.settings,
        embedding_provider=FakeEmbeddingProvider(),
        answer_provider=app.state.answer_provider,
        graph_caller=graph_caller,
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
