from __future__ import annotations

from pathlib import Path
from typing import TypedDict
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.ingestion.pipeline import IngestionPipeline, InMemoryIngestionJobStore
from app.main import create_app


def test_import_upload_versions_existing_destination(tmp_path: Path) -> None:
    client, _store, _enqueuer = _imports_client(tmp_path)

    first_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    second_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Different", "text/plain")},
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    second_body = second_response.json()
    assert second_body["status"] == "queued"
    assert second_body["metadata"]["path_strategy"] == "content_hash_suffix"
    assert Path(second_body["raw_path"]).name.startswith("upload-")
    assert Path(second_body["canonical_path"]).name.startswith("upload-")


def test_import_upload_defers_invalid_utf8_to_worker(tmp_path: Path) -> None:
    client, store, enqueuer = _imports_client(tmp_path, raise_server_exceptions=False)

    response = client.post(
        "/imports",
        files={"file": ("broken.txt", b"\xff\xfe\xfa", "text/plain")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert Path(body["raw_path"]).read_bytes() == b"\xff\xfe\xfa"
    assert not Path(body["canonical_path"]).exists()
    assert store.list_recent(limit=1)[0].status == "queued"
    assert enqueuer.calls[0]["task_type"] == "ingest.upload"


def test_import_upload_requires_admin_key_when_configured(tmp_path: Path) -> None:
    client, _store, _enqueuer = _imports_client(tmp_path, admin_api_key="secret")

    unauthorized_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    authorized_response = client.post(
        "/imports",
        headers={"X-KB-Admin-Key": "secret"},
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert unauthorized_response.status_code == 401
    assert authorized_response.status_code == 202


def test_import_job_status_and_retry_require_admin_key_when_configured(tmp_path: Path) -> None:
    client, _store, _enqueuer = _imports_client(tmp_path, admin_api_key="secret")

    authorized_upload = client.post(
        "/imports",
        headers={"X-KB-Admin-Key": "secret"},
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    job_id = authorized_upload.json()["id"]

    unauthorized_status = client.get("/imports/status")
    authorized_status = client.get("/imports/status", headers={"X-KB-Admin-Key": "secret"})
    unauthorized_retry = client.post(f"/imports/{job_id}/retry")

    assert unauthorized_status.status_code == 401
    assert authorized_status.status_code == 200
    assert unauthorized_retry.status_code == 401


def test_import_upload_rejects_oversized_file(tmp_path: Path) -> None:
    client, _store, _enqueuer = _imports_client(tmp_path, max_upload_bytes=4)

    response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"too large", "text/plain")},
    )

    assert response.status_code == 413


def test_import_upload_rejects_content_type_extension_mismatch(tmp_path: Path) -> None:
    client, store, enqueuer = _imports_client(tmp_path)

    response = client.post(
        "/imports",
        files={"file": ("guide.pdf", b"%PDF-1.4\n", "text/plain")},
    )

    assert response.status_code == 400
    assert "content type" in response.json()["detail"]
    assert store.list_recent(limit=1) == []
    assert enqueuer.calls == []


def test_import_upload_returns_queued_job_status_and_can_fetch_job(tmp_path: Path) -> None:
    client, _store, enqueuer = _imports_client(tmp_path)

    response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["id"]
    assert body["status"] == "queued"
    assert body["kind"] == "upload"
    assert body["content_hash"]
    assert body["size_bytes"] == len(b"Question\n\nAnswer")
    assert Path(body["raw_path"]).read_bytes() == b"Question\n\nAnswer"
    assert not Path(body["canonical_path"]).exists()
    assert body["metadata"]["background_job_id"] == str(enqueuer.calls[0]["job_id"])
    assert enqueuer.calls[0]["task_type"] == "ingest.upload"
    assert enqueuer.calls[0]["payload"]["ingestion_job_id"] == body["id"]

    status_response = client.get(f"/imports/{body['id']}")
    assert status_response.status_code == 200
    assert status_response.json()["id"] == body["id"]


def test_import_upload_marks_job_failed_when_background_enqueue_fails(tmp_path: Path) -> None:
    client, store, enqueuer = _imports_client(tmp_path, raise_server_exceptions=False)
    enqueuer.fail = True

    response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert response.status_code == 503
    assert "Could not queue import job" in response.json()["detail"]
    failed_job = store.list_recent(limit=1)[0]
    assert failed_job.status == "failed"
    assert "Background job enqueue failed" in (failed_job.error or "")
    assert failed_job.raw_path is not None
    assert Path(failed_job.raw_path).read_bytes() == b"Question\n\nAnswer"
    assert failed_job.canonical_path is not None
    assert not Path(failed_job.canonical_path).exists()


def test_import_upload_deduplicates_same_content(tmp_path: Path) -> None:
    client, store, _enqueuer = _imports_client(tmp_path)

    first_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    first_body = first_response.json()
    store.mark_succeeded(
        UUID(first_body["id"]),
        raw_path=first_body["raw_path"],
        canonical_path=first_body["canonical_path"],
    )
    second_response = client.post(
        "/imports",
        files={"file": ("copy.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 200
    second_body = second_response.json()
    assert second_body["status"] == "duplicate"
    assert second_body["canonical_path"] == first_body["canonical_path"]
    assert not (tmp_path / "raw" / "copy.txt").exists()


def test_import_upload_deduplicates_same_content_while_original_is_queued(
    tmp_path: Path,
) -> None:
    client, _store, enqueuer = _imports_client(tmp_path)

    first_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    second_response = client.post(
        "/imports",
        files={"file": ("copy.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 200
    first_body = first_response.json()
    second_body = second_response.json()
    assert second_body["status"] == "duplicate"
    assert second_body["canonical_path"] == first_body["canonical_path"]
    assert second_body["metadata"]["duplicate_of"] == first_body["id"]
    assert len(enqueuer.calls) == 1
    assert not (tmp_path / "raw" / "copy.txt").exists()


def test_failed_import_job_can_be_requeued_for_retry(tmp_path: Path) -> None:
    client, store, enqueuer = _imports_client(tmp_path, raise_server_exceptions=False)

    response = client.post(
        "/imports",
        files={"file": ("broken.txt", b"\xff\xfe", "text/plain")},
    )
    body = response.json()
    store.mark_failed(
        UUID(body["id"]),
        error="UnicodeDecodeError: invalid utf-8",
        raw_path=body["raw_path"],
        canonical_path=body["canonical_path"],
    )

    assert response.status_code == 202
    status_response = client.get("/imports/status")
    assert status_response.status_code == 200
    failed_job = status_response.json()["jobs"][0]
    assert failed_job["status"] == "failed"
    assert Path(failed_job["raw_path"]).read_bytes() == b"\xff\xfe"

    retry_response = client.post(f"/imports/{failed_job['id']}/retry")
    assert retry_response.status_code == 202
    retry_body = retry_response.json()
    assert retry_body["status"] == "queued"
    assert retry_body["metadata"]["retried"] is True
    assert enqueuer.calls[-1]["task_type"] == "ingest.upload"


def test_failed_import_retry_stays_failed_when_background_enqueue_fails(
    tmp_path: Path,
) -> None:
    client, store, enqueuer = _imports_client(tmp_path, raise_server_exceptions=False)

    response = client.post(
        "/imports",
        files={"file": ("broken.txt", b"\xff\xfe", "text/plain")},
    )
    body = response.json()
    store.mark_failed(
        UUID(body["id"]),
        error="UnicodeDecodeError: invalid utf-8",
        raw_path=body["raw_path"],
        canonical_path=body["canonical_path"],
    )
    enqueuer.fail = True

    retry_response = client.post(f"/imports/{body['id']}/retry")

    assert retry_response.status_code == 503
    failed_job = store.get(UUID(body["id"]))
    assert failed_job is not None
    assert failed_job.status == "failed"
    assert "Background job enqueue failed" in (failed_job.error or "")

    enqueuer.fail = False
    second_retry_response = client.post(f"/imports/{body['id']}/retry")
    assert second_retry_response.status_code == 202
    assert second_retry_response.json()["status"] == "queued"


def _imports_client(
    tmp_path: Path,
    *,
    raise_server_exceptions: bool = True,
    admin_api_key: str | None = None,
    max_upload_bytes: int = 10_000_000,
) -> tuple[TestClient, InMemoryIngestionJobStore, CapturingBackgroundJobEnqueuer]:
    settings = Settings(
        docs_dir=str(tmp_path / "docs"),
        raw_dir=str(tmp_path / "raw"),
        kb_dir=str(tmp_path / ".kb"),
        embedding_provider="fake",
        answer_provider="fake",
        admin_api_key=admin_api_key,
        max_upload_bytes=max_upload_bytes,
    )
    store = InMemoryIngestionJobStore()
    enqueuer = CapturingBackgroundJobEnqueuer()
    app = create_app(settings=settings)
    app.state.ingestion_pipeline_factory = lambda: IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )
    app.state.background_job_enqueuer = enqueuer
    return TestClient(
        app,
        raise_server_exceptions=raise_server_exceptions,
    ), store, enqueuer


class EnqueuedBackgroundJobCall(TypedDict):
    job_id: UUID
    task_type: str
    payload: dict[str, object]
    priority: int
    max_attempts: int


class CapturingBackgroundJobEnqueuer:
    def __init__(self) -> None:
        self.calls: list[EnqueuedBackgroundJobCall] = []
        self.fail = False

    def __call__(
        self,
        *,
        task_type: str,
        payload: dict[str, object],
        priority: int = 100,
        max_attempts: int = 3,
    ) -> UUID:
        if self.fail:
            raise RuntimeError("background queue unavailable")
        job_id = uuid4()
        self.calls.append(
            {
                "job_id": job_id,
                "task_type": task_type,
                "payload": payload,
                "priority": priority,
                "max_attempts": max_attempts,
            }
        )
        return job_id
