from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.ingestion.pipeline import IngestionPipeline, InMemoryIngestionJobStore
from app.main import create_app


def test_import_upload_rejects_existing_destination(tmp_path: Path) -> None:
    client, _store = _imports_client(tmp_path)

    first_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    second_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Different", "text/plain")},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert "already exists" in second_response.json()["detail"]


def test_import_upload_rejects_invalid_utf8(tmp_path: Path) -> None:
    client, store = _imports_client(tmp_path, raise_server_exceptions=False)

    response = client.post(
        "/imports",
        files={"file": ("broken.txt", b"\xff\xfe\xfa", "text/plain")},
    )

    assert response.status_code == 400
    assert "Could not import file" in response.json()["detail"]
    assert store.list_recent(limit=1)[0].status == "failed"


def test_import_upload_requires_admin_key_when_configured(tmp_path: Path) -> None:
    client, _store = _imports_client(tmp_path, admin_api_key="secret")

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
    assert authorized_response.status_code == 200


def test_import_job_status_and_retry_require_admin_key_when_configured(tmp_path: Path) -> None:
    client, _store = _imports_client(tmp_path, admin_api_key="secret")

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
    client, _store = _imports_client(tmp_path, max_upload_bytes=4)

    response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"too large", "text/plain")},
    )

    assert response.status_code == 413


def test_import_upload_returns_job_status_and_can_fetch_job(tmp_path: Path) -> None:
    client, _store = _imports_client(tmp_path)

    response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"]
    assert body["status"] == "succeeded"
    assert body["kind"] == "upload"
    assert body["content_hash"]
    assert body["size_bytes"] == len(b"Question\n\nAnswer")

    status_response = client.get(f"/imports/{body['id']}")
    assert status_response.status_code == 200
    assert status_response.json()["id"] == body["id"]


def test_import_upload_deduplicates_same_content(tmp_path: Path) -> None:
    client, _store = _imports_client(tmp_path)

    first_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    second_response = client.post(
        "/imports",
        files={"file": ("copy.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_body = first_response.json()
    second_body = second_response.json()
    assert second_body["status"] == "duplicate"
    assert second_body["canonical_path"] == first_body["canonical_path"]
    assert not (tmp_path / "raw" / "copy.txt").exists()


def test_failed_import_job_can_be_inspected_and_retry_reports_failure(tmp_path: Path) -> None:
    client, _store = _imports_client(tmp_path, raise_server_exceptions=False)

    response = client.post(
        "/imports",
        files={"file": ("broken.txt", b"\xff\xfe", "text/plain")},
    )

    assert response.status_code == 400
    status_response = client.get("/imports/status")
    assert status_response.status_code == 200
    failed_job = status_response.json()["jobs"][0]
    assert failed_job["status"] == "failed"
    assert Path(failed_job["raw_path"]).read_bytes() == b"\xff\xfe"

    retry_response = client.post(f"/imports/{failed_job['id']}/retry")
    assert retry_response.status_code == 400
    assert "Could not import file" in retry_response.json()["detail"]


def _imports_client(
    tmp_path: Path,
    *,
    raise_server_exceptions: bool = True,
    admin_api_key: str | None = None,
    max_upload_bytes: int = 10_000_000,
) -> tuple[TestClient, InMemoryIngestionJobStore]:
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
    app = create_app(settings=settings)
    app.state.ingestion_pipeline_factory = lambda: IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )
    return TestClient(
        app,
        raise_server_exceptions=raise_server_exceptions,
    ), store
