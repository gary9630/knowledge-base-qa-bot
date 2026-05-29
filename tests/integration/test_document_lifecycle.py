from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.tables import AuditEvent


def test_admin_document_lifecycle_disable_delete_and_reindex(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    source_path = docs_dir / "course.md"
    source_path.write_text(
        "# Course Site\n\nThe course website is https://example.test/.\n",
        encoding="utf-8",
    )
    client = TestClient(_lifecycle_app(db_session, tmp_path))
    admin_headers = {"X-KB-Admin-Key": "secret"}

    index_response = client.post("/index", headers=admin_headers)
    documents_response = client.get("/admin/documents", headers=admin_headers)
    document = documents_response.json()["documents"][0]
    document_id = document["id"]
    visible_sources = client.get("/sources")
    searchable = client.post("/search", json={"query": "course website", "strategy": "markdown"})

    assert index_response.status_code == 200
    assert documents_response.status_code == 200
    assert document["filename"] == "course.md"
    assert document["lifecycle_status"] == "active"
    assert document["index_status"] == "indexed"
    assert document["canonical_exists"] is True
    assert document["section_count"] == 1
    assert document["chunk_count"] >= 1
    assert [item["filename"] for item in visible_sources.json()["documents"]] == ["course.md"]
    assert searchable.json()["decision"] == "can_answer"

    disable_response = client.patch(
        f"/admin/documents/{document_id}/lifecycle",
        headers=admin_headers,
        json={"status": "disabled", "reason": "outdated"},
    )
    hidden_sources = client.get("/sources")
    hidden_search = client.post(
        "/search",
        json={"query": "course website", "strategy": "markdown"},
    )
    hidden_mindmap = client.get("/mindmap")

    assert disable_response.status_code == 200
    assert disable_response.json()["lifecycle_status"] == "disabled"
    assert disable_response.json()["lifecycle_reason"] == "outdated"
    assert hidden_sources.json()["documents"] == []
    assert hidden_search.json()["decision"] == "cannot_confirm"
    assert hidden_mindmap.json()["stats"] == {"documents": 0, "sections": 0}

    enable_response = client.patch(
        f"/admin/documents/{document_id}/lifecycle",
        headers=admin_headers,
        json={"status": "active"},
    )
    enabled_sources = client.get("/sources")

    assert enable_response.status_code == 200
    assert enable_response.json()["lifecycle_status"] == "active"
    assert [item["filename"] for item in enabled_sources.json()["documents"]] == ["course.md"]

    delete_response = client.delete(f"/admin/documents/{document_id}", headers=admin_headers)
    deleted_sources = client.get("/sources")

    assert delete_response.status_code == 200
    assert delete_response.json()["lifecycle_status"] == "deleted"
    assert delete_response.json()["index_status"] == "deleted"
    assert delete_response.json()["section_count"] == 0
    assert delete_response.json()["chunk_count"] == 0
    assert source_path.exists()
    assert deleted_sources.json()["documents"] == []

    reindex_response = client.post(
        f"/admin/documents/{document_id}/reindex",
        headers=admin_headers,
    )
    restored_sources = client.get("/sources")

    assert reindex_response.status_code == 200
    assert reindex_response.json()["lifecycle_status"] == "active"
    assert reindex_response.json()["index_status"] == "indexed"
    assert reindex_response.json()["section_count"] == 1
    assert reindex_response.json()["chunk_count"] >= 1
    assert [item["filename"] for item in restored_sources.json()["documents"]] == ["course.md"]

    audit_event_types = set(
        db_session.scalars(
            select(AuditEvent.event_type).where(AuditEvent.resource_id == document_id)
        ).all()
    )
    assert {
        "document.disabled",
        "document.enabled",
        "document.deleted",
        "document.reindexed",
    }.issubset(audit_event_types)


def _lifecycle_app(db_session: Session, tmp_path: Path) -> FastAPI:
    settings = Settings(
        docs_dir=str(tmp_path / "docs"),
        raw_dir=str(tmp_path / "raw"),
        kb_dir=str(tmp_path / ".kb"),
        embedding_provider="fake",
        answer_provider="fake",
        admin_api_key="secret",
    )
    return create_app(settings=settings, session_factory=_session_factory(db_session))


def _session_factory(db_session: Session) -> Callable[[], Session]:
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return create_session
