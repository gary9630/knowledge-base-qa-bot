from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_import_upload_rejects_existing_destination(tmp_path: Path) -> None:
    client = _imports_client(tmp_path)

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
    client = _imports_client(tmp_path, raise_server_exceptions=False)

    response = client.post(
        "/imports",
        files={"file": ("broken.txt", b"\xff\xfe\xfa", "text/plain")},
    )

    assert response.status_code == 400
    assert "Could not import file" in response.json()["detail"]


def test_import_upload_requires_admin_key_when_configured(tmp_path: Path) -> None:
    client = _imports_client(tmp_path, admin_api_key="secret")

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


def test_import_upload_rejects_oversized_file(tmp_path: Path) -> None:
    client = _imports_client(tmp_path, max_upload_bytes=4)

    response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"too large", "text/plain")},
    )

    assert response.status_code == 413


def _imports_client(
    tmp_path: Path,
    *,
    raise_server_exceptions: bool = True,
    admin_api_key: str | None = None,
    max_upload_bytes: int = 10_000_000,
) -> TestClient:
    settings = Settings(
        docs_dir=str(tmp_path / "docs"),
        raw_dir=str(tmp_path / "raw"),
        kb_dir=str(tmp_path / ".kb"),
        embedding_provider="fake",
        answer_provider="fake",
        admin_api_key=admin_api_key,
        max_upload_bytes=max_upload_bytes,
    )
    return TestClient(
        create_app(settings=settings),
        raise_server_exceptions=raise_server_exceptions,
    )
