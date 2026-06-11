from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import (
    Concept,
    ConceptCluster,
    ConceptEdge,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)
from scripts.seed_concept_graph import apply_seed_graph, parse_seed_graph

# ---------------------------------------------------------------------------
# Helpers — matching the pattern from tests/integration/test_concept_tables.py
# ---------------------------------------------------------------------------


def _document(
    db_session: Session,
    *,
    filename: str = "course.md",
    content_hash: str = "doc-hash-v1",
) -> Document:
    document = Document(
        filename=filename,
        canonical_path=f"/docs/{filename}",
        source_type="markdown",
        content_hash=content_hash,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _section(
    db_session: Session,
    document: Document,
    *,
    slug: str,
    position: int,
) -> Section:
    section = Section(
        document_id=document.id,
        source_id=f"{document.filename}#{slug}",
        heading=slug,
        heading_slug=slug,
        level=2,
        body_md=f"關於 {slug} 的內容。",
        token_count=8,
        content_hash=f"hash-{slug}",
        position=position,
    )
    db_session.add(section)
    db_session.flush()
    return section


def _seed_payload(
    source_id_a: str,
    source_id_b: str,
) -> dict:  # type: ignore[type-arg]
    return {
        "version": 1,
        "clusters": [{"name": "快取", "position": 0}],
        "concepts": [
            {
                "name": "Consistent Hashing",
                "slug": "consistent-hashing",
                "summary": "把節點與鍵映射到同一個雜湊環。",
                "aliases": ["一致性雜湊"],
                "cluster": "快取",
                "source_ids": [source_id_a],
            },
            {
                "name": "Sharding",
                "slug": "sharding",
                "summary": "資料水平切分。",
                "aliases": [],
                "cluster": "快取",
                "source_ids": [source_id_b],
            },
        ],
        "edges": [
            {"source": "consistent-hashing", "target": "sharding", "kind": "related"},
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_strict_bogus_source_raises_with_id_in_message(db_session: Session) -> None:
    document = _document(db_session)
    real_section = _section(db_session, document, slug="consistent-hashing", position=0)

    payload = _seed_payload(real_section.source_id, "course.md#bogus-nonexistent-id")
    seed = parse_seed_graph(payload)

    with pytest.raises(ValueError, match="bogus-nonexistent-id"):
        apply_seed_graph(db_session, seed, strict=True)


def test_apply_seed_graph_creates_all_rows_and_extraction_state(db_session: Session) -> None:
    document = _document(db_session, content_hash="doc-hash-v1")
    sec_a = _section(db_session, document, slug="consistent-hashing", position=0)
    sec_b = _section(db_session, document, slug="sharding", position=1)

    payload = _seed_payload(sec_a.source_id, sec_b.source_id)
    seed = parse_seed_graph(payload)
    counts = apply_seed_graph(db_session, seed, strict=True)

    # clusters
    clusters = db_session.scalars(select(ConceptCluster)).all()
    assert len(clusters) == 1
    assert clusters[0].name == "快取"

    # concepts
    concepts = db_session.scalars(select(Concept)).all()
    assert len(concepts) == 2
    slugs = {c.slug for c in concepts}
    assert slugs == {"consistent-hashing", "sharding"}

    # sources
    sources = db_session.scalars(select(ConceptSource)).all()
    assert len(sources) == 2

    # edges
    edges = db_session.scalars(select(ConceptEdge)).all()
    assert len(edges) == 1
    assert edges[0].kind == "related"

    # extraction state — uses document's CURRENT content_hash
    states = db_session.scalars(select(ConceptExtractionState)).all()
    assert len(states) == 1
    assert states[0].document_id == document.id
    assert states[0].content_hash == document.content_hash

    # counts dict
    assert counts["clusters"] >= 1
    assert counts["concepts"] >= 2
    assert counts["edges"] >= 1
    assert counts["extraction_states"] >= 1


def test_apply_seed_graph_is_idempotent(db_session: Session) -> None:
    document = _document(db_session, content_hash="doc-hash-v1")
    sec_a = _section(db_session, document, slug="consistent-hashing", position=0)
    sec_b = _section(db_session, document, slug="sharding", position=1)

    payload = _seed_payload(sec_a.source_id, sec_b.source_id)
    seed = parse_seed_graph(payload)

    counts_first = apply_seed_graph(db_session, seed, strict=True)
    counts_second = apply_seed_graph(db_session, seed, strict=True)

    # Counts should be the same on both runs (upserts — no new rows created)
    assert counts_first == counts_second

    # No duplicate rows
    assert len(db_session.scalars(select(ConceptCluster)).all()) == 1
    assert len(db_session.scalars(select(Concept)).all()) == 2
    assert len(db_session.scalars(select(ConceptEdge)).all()) == 1
    assert len(db_session.scalars(select(ConceptSource)).all()) == 2
    assert len(db_session.scalars(select(ConceptExtractionState)).all()) == 1


def test_apply_seed_graph_update_updates_concept_in_place(db_session: Session) -> None:
    """Re-applying with a changed summary updates the concept in-place."""
    document = _document(db_session, content_hash="doc-hash-v1")
    sec_a = _section(db_session, document, slug="consistent-hashing", position=0)
    sec_b = _section(db_session, document, slug="sharding", position=1)

    payload = _seed_payload(sec_a.source_id, sec_b.source_id)
    seed_v1 = parse_seed_graph(payload)
    apply_seed_graph(db_session, seed_v1, strict=True)

    # Change the summary
    updated_payload = _seed_payload(sec_a.source_id, sec_b.source_id)
    updated_payload["concepts"][0]["summary"] = "新的摘要：更新後的描述。"
    seed_v2 = parse_seed_graph(updated_payload)
    apply_seed_graph(db_session, seed_v2, strict=True)

    concept = db_session.scalar(
        select(Concept).where(Concept.slug == "consistent-hashing")
    )
    assert concept is not None
    assert concept.summary == "新的摘要：更新後的描述。"
    # Still only one row per concept
    assert len(db_session.scalars(select(Concept)).all()) == 2
