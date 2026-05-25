from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.tables import Document, Section


def test_mindmap_returns_empty_graph_for_empty_database(db_session: Session) -> None:
    client = TestClient(_app_with_session(db_session))

    response = client.get("/mindmap")

    assert response.status_code == 200
    assert response.json() == {
        "nodes": [],
        "edges": [],
        "stats": {
            "documents": 0,
            "sections": 0,
        },
    }


def test_mindmap_returns_document_and_section_nodes(db_session: Session) -> None:
    document = Document(
        filename="operator-guide.md",
        canonical_path="docs/operator-guide.md",
        source_type="markdown",
        title="Operator Guide",
        content_hash="doc-hash",
        imported_from="sample-docs/operator-guide.md",
        metadata_json={"collection": "ops"},
    )
    overview = Section(
        document=document,
        source_id="operator-guide.md#overview",
        heading="Overview",
        heading_slug="overview",
        level=2,
        body_md="## Overview\n\nKeep the index current.",
        token_count=7,
        content_hash="section-hash-overview",
        metadata_json={"rank": 1},
    )
    troubleshooting = Section(
        document=document,
        source_id="operator-guide.md#troubleshooting",
        heading="Troubleshooting",
        heading_slug="troubleshooting",
        level=2,
        body_md="## Troubleshooting\n\nCheck ingestion jobs.",
        token_count=6,
        content_hash="section-hash-troubleshooting",
        metadata_json={"rank": 2},
    )
    db_session.add_all([document, overview, troubleshooting])
    db_session.commit()

    client = TestClient(_app_with_session(db_session))

    response = client.get("/mindmap")

    assert response.status_code == 200
    body = response.json()
    document_id = str(document.id)
    overview_id = str(overview.id)
    troubleshooting_id = str(troubleshooting.id)

    assert body["stats"] == {
        "documents": 1,
        "sections": 2,
    }
    assert body["nodes"] == [
        {
            "id": f"document:{document_id}",
            "type": "document",
            "label": "Operator Guide",
            "metadata": {
                "document_id": document_id,
                "filename": "operator-guide.md",
                "title": "Operator Guide",
                "source_type": "markdown",
                "imported_from": "sample-docs/operator-guide.md",
                "section_count": 2,
            },
        },
        {
            "id": f"section:{overview_id}",
            "type": "section",
            "label": "Overview",
            "metadata": {
                "document_id": document_id,
                "section_id": overview_id,
                "source_id": "operator-guide.md#overview",
                "heading": "Overview",
                "heading_slug": "overview",
                "level": 2,
                "token_count": 7,
            },
        },
        {
            "id": f"section:{troubleshooting_id}",
            "type": "section",
            "label": "Troubleshooting",
            "metadata": {
                "document_id": document_id,
                "section_id": troubleshooting_id,
                "source_id": "operator-guide.md#troubleshooting",
                "heading": "Troubleshooting",
                "heading_slug": "troubleshooting",
                "level": 2,
                "token_count": 6,
            },
        },
    ]
    assert body["edges"] == [
        {
            "id": f"edge:{document_id}:{overview_id}",
            "source": f"document:{document_id}",
            "target": f"section:{overview_id}",
            "relation": "contains",
        },
        {
            "id": f"edge:{document_id}:{troubleshooting_id}",
            "source": f"document:{document_id}",
            "target": f"section:{troubleshooting_id}",
            "relation": "contains",
        },
    ]

    UUID(document_id)
    UUID(overview_id)
    UUID(troubleshooting_id)


def _app_with_session(db_session: Session) -> FastAPI:
    return create_app(
        settings=Settings(embedding_provider="fake", answer_provider="fake"),
        session_factory=_session_factory(db_session),
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
