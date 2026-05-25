from uuid import UUID

from app.api.mindmap import build_mindmap_response
from app.models.tables import Document, Section


def test_build_mindmap_response_returns_stable_document_section_graph() -> None:
    document = Document(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        filename="guide.md",
        canonical_path="docs/guide.md",
        source_type="markdown",
        title=None,
        content_hash="doc-hash",
        imported_from=None,
    )
    Section(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        document=document,
        source_id="guide.md#child",
        heading="Child",
        heading_slug="child",
        level=2,
        body_md="## Child",
        token_count=3,
        content_hash="child-hash",
    )
    Section(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        document=document,
        source_id="guide.md#parent",
        heading="Parent",
        heading_slug="parent",
        level=1,
        body_md="# Parent",
        token_count=2,
        content_hash="parent-hash",
    )

    response = build_mindmap_response([document])

    assert response.model_dump() == {
        "nodes": [
            {
                "id": "document:00000000-0000-0000-0000-000000000001",
                "type": "document",
                "label": "guide.md",
                "metadata": {
                    "document_id": "00000000-0000-0000-0000-000000000001",
                    "filename": "guide.md",
                    "title": None,
                    "source_type": "markdown",
                    "imported_from": None,
                    "section_count": 2,
                },
            },
            {
                "id": "section:00000000-0000-0000-0000-000000000002",
                "type": "section",
                "label": "Parent",
                "metadata": {
                    "document_id": "00000000-0000-0000-0000-000000000001",
                    "section_id": "00000000-0000-0000-0000-000000000002",
                    "source_id": "guide.md#parent",
                    "heading": "Parent",
                    "heading_slug": "parent",
                    "level": 1,
                    "token_count": 2,
                },
            },
            {
                "id": "section:00000000-0000-0000-0000-000000000003",
                "type": "section",
                "label": "Child",
                "metadata": {
                    "document_id": "00000000-0000-0000-0000-000000000001",
                    "section_id": "00000000-0000-0000-0000-000000000003",
                    "source_id": "guide.md#child",
                    "heading": "Child",
                    "heading_slug": "child",
                    "level": 2,
                    "token_count": 3,
                },
            },
        ],
        "edges": [
            {
                "id": (
                    "edge:00000000-0000-0000-0000-000000000001:"
                    "00000000-0000-0000-0000-000000000002"
                ),
                "source": "document:00000000-0000-0000-0000-000000000001",
                "target": "section:00000000-0000-0000-0000-000000000002",
                "relation": "contains",
            },
            {
                "id": (
                    "edge:00000000-0000-0000-0000-000000000001:"
                    "00000000-0000-0000-0000-000000000003"
                ),
                "source": "document:00000000-0000-0000-0000-000000000001",
                "target": "section:00000000-0000-0000-0000-000000000003",
                "relation": "contains",
            },
        ],
        "stats": {
            "documents": 1,
            "sections": 2,
        },
    }
