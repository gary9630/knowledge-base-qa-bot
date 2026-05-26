from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.tables import Document, Feedback, IngestionJob, Section


@pytest.fixture
def app_with_test_db(db_session: Session, tmp_path: Path) -> FastAPI:
    docs_dir = tmp_path / "docs"
    raw_dir = tmp_path / "raw"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    (docs_dir / "常見問題FAQ.md").write_text(
        "# FAQ\n\n"
        "## 課程網站\n\n"
        "課程網站是 https://buildmoat.org/\n\n"
        "## 作業繳交\n\n"
        "請依公告時間繳交作業。\n",
        encoding="utf-8",
    )

    settings = Settings(
        docs_dir=str(docs_dir),
        raw_dir=str(raw_dir),
        kb_dir=str(kb_dir),
        embedding_provider="fake",
        answer_provider="fake",
    )
    app = create_app(settings=settings, session_factory=_session_factory(db_session))
    return app


def test_chat_before_index_returns_not_indexed(app_with_test_db: FastAPI) -> None:
    client = TestClient(app_with_test_db)

    response = client.post("/chat", json={"query": "課程網站在哪？"})

    assert response.status_code == 200
    assert response.json()["answer"] == "知識庫尚未建立索引，請先建立索引。"


def test_index_search_chat_sources_and_feedback_workflow(
    app_with_test_db: FastAPI,
    db_session: Session,
) -> None:
    client = TestClient(app_with_test_db)

    ready_before = client.get("/ready")
    assert ready_before.status_code == 503
    assert ready_before.json()["database"] is True
    assert ready_before.json()["index"] is False

    index_response = client.post("/index")
    assert index_response.status_code == 200
    index_body = index_response.json()
    assert index_body["status"] == "succeeded"
    assert index_body["files_indexed"] == 1
    assert index_body["chunks_indexed"] >= 1

    status_response = client.get("/index/status")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "succeeded"
    assert status_body["stats"]["files_indexed"] == 1

    ready_after = client.get("/ready")
    assert ready_after.status_code == 200
    assert ready_after.json()["ready"] is True

    search_response = client.post("/search", json={"query": "課程網站在哪？", "limit": 3})
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["decision"] == "can_answer"
    assert search_body["candidates"][0]["source_id"] == "常見問題FAQ.md#課程網站"

    markdown_search_response = client.post(
        "/search",
        json={"query": "課程網站在哪？", "strategy": "markdown", "limit": 3},
    )
    assert markdown_search_response.status_code == 200
    assert markdown_search_response.json()["candidates"][0]["strategy"] == "markdown"

    chat_response = client.post("/chat", json={"query": "課程網站在哪？"})
    assert chat_response.status_code == 200
    chat_body = chat_response.json()
    assert "常見問題FAQ.md#課程網站" in chat_body["answer"]
    assert chat_body["sources"][0]["source_id"] == "常見問題FAQ.md#課程網站"
    assert chat_body["assistant_message_id"]

    sources_response = client.get("/sources")
    assert sources_response.status_code == 200
    sources_body = sources_response.json()
    assert sources_body["documents"][0]["filename"] == "常見問題FAQ.md"
    document_id = sources_body["documents"][0]["id"]

    document_response = client.get(f"/sources/{document_id}")
    assert document_response.status_code == 200
    document_body = document_response.json()
    assert document_body["filename"] == "常見問題FAQ.md"
    section_id = document_body["sections"][0]["id"]

    section_response = client.get(f"/sources/{document_id}/sections/{section_id}")
    assert section_response.status_code == 200
    assert section_response.json()["source_id"].startswith("常見問題FAQ.md#")

    feedback_response = client.post(
        "/feedback",
        json={
            "message_id": chat_body["assistant_message_id"],
            "rating": 1,
            "reason": "helpful",
            "expected_source": "常見問題FAQ.md#課程網站",
            "note": "cited the right section",
        },
    )
    assert feedback_response.status_code == 200
    feedback_body = feedback_response.json()
    assert feedback_body["rating"] == 1

    feedback = db_session.scalar(select(Feedback).where(Feedback.id == UUID(feedback_body["id"])))
    assert feedback is not None
    assert feedback.message_id == UUID(chat_body["assistant_message_id"])

    user_feedback_response = client.post(
        "/feedback",
        json={
            "message_id": chat_body["user_message_id"],
            "rating": 1,
        },
    )
    assert user_feedback_response.status_code == 400


def test_ready_reports_operational_checks(app_with_test_db: FastAPI) -> None:
    client = TestClient(app_with_test_db)

    ready_before = client.get("/ready")
    client.post("/index")
    ready_after = client.get("/ready")

    assert ready_before.status_code == 503
    before_body = ready_before.json()
    assert before_body["database"] is True
    assert before_body["index"] is False
    assert before_body["ready"] is False
    assert before_body["checks"]["database"]["ok"] is True
    assert before_body["checks"]["pgvector"]["ok"] is True
    assert before_body["checks"]["migrations"]["ok"] is True
    assert before_body["checks"]["migrations"]["current_revision"]
    assert before_body["checks"]["migrations"]["head_revision"]
    assert before_body["checks"]["index"]["ok"] is False
    assert before_body["checks"]["platform_auth"]["ok"] is True

    assert ready_after.status_code == 200
    after_body = ready_after.json()
    assert after_body["ready"] is True
    assert after_body["checks"]["index"]["ok"] is True


def test_ready_reports_missing_platform_auth_in_production(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="production",
        docs_dir=str(tmp_path / "docs"),
        raw_dir=str(tmp_path / "raw"),
        kb_dir=str(tmp_path / ".kb"),
        embedding_provider="fake",
        answer_provider="fake",
    )
    app = create_app(settings=settings, session_factory=_session_factory(db_session))
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["checks"]["platform_auth"] == {
        "ok": False,
        "detail": "Platform auth is required but not configured.",
    }


def test_imports_upload_saves_raw_file_and_canonical_markdown(
    app_with_test_db: FastAPI,
    db_session: Session,
) -> None:
    client = TestClient(app_with_test_db)

    response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"]
    assert body["status"] == "succeeded"
    assert body["filename"] == "upload.txt"
    assert Path(body["raw_path"]).read_bytes() == b"Question\n\nAnswer"
    canonical_markdown = Path(body["canonical_path"]).read_text(encoding="utf-8")
    assert "source_original: raw/upload.txt" in canonical_markdown
    assert f"content_hash: {body['content_hash']}" in canonical_markdown
    assert "# upload" in canonical_markdown

    job = db_session.get(IngestionJob, UUID(body["id"]))
    assert job is not None
    assert job.status == "succeeded"
    assert job.content_hash == body["content_hash"]
    assert job.raw_path == body["raw_path"]
    assert job.canonical_path == body["canonical_path"]


def test_imports_upload_deduplicates_by_content_hash(
    app_with_test_db: FastAPI,
    db_session: Session,
) -> None:
    client = TestClient(app_with_test_db)

    first_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    duplicate_response = client.post(
        "/imports",
        files={"file": ("copy.txt", b"Question\n\nAnswer", "text/plain")},
    )

    assert first_response.status_code == 200
    assert duplicate_response.status_code == 200
    first_body = first_response.json()
    duplicate_body = duplicate_response.json()
    assert duplicate_body["status"] == "duplicate"
    assert duplicate_body["canonical_path"] == first_body["canonical_path"]
    assert duplicate_body["metadata"]["duplicate_of"] == first_body["id"]
    assert not Path(duplicate_body["raw_path"]).with_name("copy.txt").exists()

    jobs = db_session.scalars(select(IngestionJob).order_by(IngestionJob.created_at.asc())).all()
    assert [job.status for job in jobs] == ["succeeded", "duplicate"]


def test_imported_upload_enters_db_index_with_canonical_metadata(
    app_with_test_db: FastAPI,
    db_session: Session,
) -> None:
    client = TestClient(app_with_test_db)

    import_response = client.post(
        "/imports",
        files={"file": ("upload.txt", b"Question\n\nAnswer", "text/plain")},
    )
    index_response = client.post("/index")

    assert import_response.status_code == 200
    assert index_response.status_code == 200
    import_body = import_response.json()
    document = db_session.scalar(select(Document).where(Document.filename == "upload.md"))
    assert document is not None
    assert document.source_type == "imported"
    assert document.imported_from == "raw/upload.txt"
    assert document.metadata_json["content_hash"] == import_body["content_hash"]
    assert document.metadata_json["canonical_path"] == import_body["canonical_path"]


def test_sources_endpoints_hide_non_public_documents(
    app_with_test_db: FastAPI,
    db_session: Session,
) -> None:
    public_document = Document(
        filename="public.md",
        canonical_path="docs/public.md",
        source_type="markdown",
        title="Public",
        content_hash="public-hash",
    )
    public_section = Section(
        document=public_document,
        source_id="public.md#public",
        heading="Public",
        heading_slug="public",
        level=1,
        body_md="# Public\n\nVisible",
        token_count=3,
        content_hash="public-section-hash",
    )
    staff_document = Document(
        filename="staff.md",
        canonical_path="docs/staff.md",
        source_type="markdown",
        title="Staff",
        content_hash="staff-hash",
        visibility=["staff"],
    )
    staff_section = Section(
        document=staff_document,
        source_id="staff.md#staff",
        heading="Staff",
        heading_slug="staff",
        level=1,
        body_md="# Staff\n\nHidden",
        token_count=3,
        content_hash="staff-section-hash",
    )
    db_session.add_all([public_document, public_section, staff_document, staff_section])
    db_session.commit()
    client = TestClient(app_with_test_db)

    list_response = client.get("/sources")
    assert list_response.status_code == 200
    assert [document["filename"] for document in list_response.json()["documents"]] == [
        "public.md",
    ]

    public_response = client.get(f"/sources/{public_document.id}")
    assert public_response.status_code == 200

    staff_response = client.get(f"/sources/{staff_document.id}")
    assert staff_response.status_code == 404

    staff_section_response = client.get(f"/sources/{staff_document.id}/sections/{staff_section.id}")
    assert staff_section_response.status_code == 404


def _session_factory(db_session: Session) -> Callable[[], Session]:
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return create_session
