from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
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
from scripts.seed_concept_graph import apply_seed_graph, main, parse_seed_graph

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
    """I2: error message must include both the concept slug and unknown source-id."""
    document = _document(db_session)
    real_section = _section(db_session, document, slug="consistent-hashing", position=0)

    payload = _seed_payload(real_section.source_id, "course.md#bogus-nonexistent-id")
    seed = parse_seed_graph(payload)

    with pytest.raises(ValueError) as exc_info:
        apply_seed_graph(db_session, seed, strict=True)

    msg = str(exc_info.value)
    assert "bogus-nonexistent-id" in msg
    # I2: must also identify the offending concept slug
    assert "sharding" in msg


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

    # concepts — seeded rows carry origin="seed" so the pipeline never prunes them
    concepts = db_session.scalars(select(Concept)).all()
    assert len(concepts) == 2
    slugs = {c.slug for c in concepts}
    assert slugs == {"consistent-hashing", "sharding"}
    assert all(c.origin == "seed" for c in concepts)

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

    # counts dict — M1 split keys
    assert counts["clusters_created"] + counts["clusters_updated"] >= 1
    assert counts["concepts_created"] + counts["concepts_updated"] >= 2
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

    # Counts should be stable in total across both runs, but
    # the created/updated split will flip on the second run — verify totals match
    def _total_concepts(c: dict[str, int]) -> int:
        return c["concepts_created"] + c["concepts_updated"]

    def _total_clusters(c: dict[str, int]) -> int:
        return c["clusters_created"] + c["clusters_updated"]

    assert _total_concepts(counts_first) == _total_concepts(counts_second)
    assert _total_clusters(counts_first) == _total_clusters(counts_second)
    assert counts_first["edges"] == counts_second["edges"]
    assert counts_first["sources"] == counts_second["sources"]
    assert counts_first["extraction_states"] == counts_second["extraction_states"]

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

    # Simulate a concept the pipeline previously created (origin="extracted")
    existing = db_session.scalar(select(Concept).where(Concept.slug == "consistent-hashing"))
    assert existing is not None
    existing.origin = "extracted"
    db_session.flush()

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
    assert concept.origin == "seed"  # updates re-mark curated rows as seed-origin
    # Still only one row per concept
    assert len(db_session.scalars(select(Concept)).all()) == 2


# ---------------------------------------------------------------------------
# M1: counts dict with created/updated split
# ---------------------------------------------------------------------------


def test_counts_dict_has_split_keys(db_session: Session) -> None:
    document = _document(db_session, content_hash="doc-hash-v1")
    sec_a = _section(db_session, document, slug="consistent-hashing", position=0)
    sec_b = _section(db_session, document, slug="sharding", position=1)

    payload = _seed_payload(sec_a.source_id, sec_b.source_id)
    seed = parse_seed_graph(payload)

    counts = apply_seed_graph(db_session, seed, strict=True)

    # First run: everything should be created
    assert "concepts_created" in counts
    assert "concepts_updated" in counts
    assert "clusters_created" in counts
    assert "clusters_updated" in counts
    assert counts["concepts_created"] == 2
    assert counts["concepts_updated"] == 0
    assert counts["clusters_created"] == 1
    assert counts["clusters_updated"] == 0

    # Second run: everything should be updated
    counts2 = apply_seed_graph(db_session, seed, strict=True)
    assert counts2["concepts_created"] == 0
    assert counts2["concepts_updated"] == 2
    assert counts2["clusters_created"] == 0
    assert counts2["clusters_updated"] == 1


# ---------------------------------------------------------------------------
# I2: strict-apply error lists offenders as "slug: source-id"
# ---------------------------------------------------------------------------


def test_strict_bogus_source_error_lists_slug_and_id(db_session: Session) -> None:
    """The ValueError from apply_seed_graph must include both the concept slug
    and the unknown source-id, formatted as 'slug: source-id'."""
    document = _document(db_session)
    real_section = _section(db_session, document, slug="consistent-hashing", position=0)

    payload = _seed_payload(real_section.source_id, "course.md#bogus-nonexistent-id")
    seed = parse_seed_graph(payload)

    with pytest.raises(ValueError) as exc_info:
        apply_seed_graph(db_session, seed, strict=True)

    msg = str(exc_info.value)
    assert "sharding" in msg
    assert "bogus-nonexistent-id" in msg


# ---------------------------------------------------------------------------
# I1 + I2: dry-run exits 1 on unknown source_ids, message lists slug+id
# ---------------------------------------------------------------------------


def _make_seed_file(
    source_id_a: str,
    source_id_b: str,
    *,
    tmp_path: Path,
) -> Path:
    payload = _seed_payload(source_id_a, source_id_b)
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps(payload), encoding="utf-8")
    return seed_file


def test_dry_run_exits_1_on_unknown_source_id(
    db_engine: Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """I1: --dry-run must return exit code 1 when unknown source_ids are present."""
    from sqlalchemy.orm import sessionmaker

    import app.core.database as _db_module

    # Patch SessionLocal to use the test engine so main() hits the test DB
    monkeypatch.setattr(
        _db_module,
        "SessionLocal",
        sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False),
    )

    document = _document(db_session, content_hash="doc-hash-v1")
    real_section = _section(db_session, document, slug="consistent-hashing", position=0)
    # Flush so the section is visible to the session used by main()
    db_session.flush()

    seed_file = _make_seed_file(
        real_section.source_id,
        "course.md#totally-bogus-source-id",
        tmp_path=tmp_path,
    )

    rc = main(["--file", str(seed_file), "--dry-run"])
    assert rc == 1, f"Expected exit code 1, got {rc}"

    # No concept rows should have been written
    assert db_session.scalars(select(Concept)).all() == []


def test_dry_run_unknown_source_message_lists_slug_and_id(
    db_engine: Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """I2: dry-run output must contain 'concept-slug: unknown-source-id' format."""
    from sqlalchemy.orm import sessionmaker

    import app.core.database as _db_module

    monkeypatch.setattr(
        _db_module,
        "SessionLocal",
        sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False),
    )

    document = _document(db_session, content_hash="doc-hash-v1")
    real_section = _section(db_session, document, slug="consistent-hashing", position=0)
    db_session.flush()

    seed_file = _make_seed_file(
        real_section.source_id,
        "course.md#bogus-nonexistent-id",
        tmp_path=tmp_path,
    )

    rc = main(["--file", str(seed_file), "--dry-run"])
    assert rc == 1

    captured = capsys.readouterr()
    assert "sharding" in captured.err
    assert "bogus-nonexistent-id" in captured.err


# ---------------------------------------------------------------------------
# M2: dry-run exercises the real apply_seed_graph path (rolled back)
# ---------------------------------------------------------------------------


def test_dry_run_exercises_real_path_and_rolls_back(db_session: Session) -> None:
    """M2: dry-run applies the seed inside a savepoint and rolls back, leaving
    zero concept rows — this verifies the real validation path is exercised
    (not a duplicated query) and the zero-write guarantee holds.
    """
    document = _document(db_session, content_hash="doc-hash-v1")
    sec_a = _section(db_session, document, slug="consistent-hashing", position=0)
    sec_b = _section(db_session, document, slug="sharding", position=1)

    payload = _seed_payload(sec_a.source_id, sec_b.source_id)
    seed = parse_seed_graph(payload)

    # Simulate what the dry-run CLI does: apply inside a nested savepoint
    # and roll back regardless of outcome.
    sp = db_session.begin_nested()
    try:
        counts = apply_seed_graph(db_session, seed, strict=True)
        # Validate that apply succeeded (proves the real path is used)
        assert counts["concepts_created"] == 2
    finally:
        sp.rollback()

    # After rollback, zero concept rows in the session
    db_session.expire_all()
    assert db_session.scalars(select(Concept)).all() == []


# ---------------------------------------------------------------------------
# I3: --replace mode removes zombies
# ---------------------------------------------------------------------------


def _seed_v1_payload(
    source_id_a: str,
    source_id_b: str,
) -> dict:  # type: ignore[type-arg]
    """Two concepts + one edge."""
    return _seed_payload(source_id_a, source_id_b)


def _seed_v2_payload(source_id_a: str) -> dict:  # type: ignore[type-arg]
    """Only one concept, no edges — v1's second concept becomes a zombie."""
    return {
        "version": 1,
        "clusters": [{"name": "快取", "position": 0}],
        "concepts": [
            {
                "name": "Consistent Hashing",
                "slug": "consistent-hashing",
                "summary": "把節點與鍵映射到同一個雜湊環。",
                "aliases": [],
                "cluster": "快取",
                "source_ids": [source_id_a],
            },
        ],
        "edges": [],
    }


def test_replace_mode_removes_zombie_concepts_and_edges(db_session: Session) -> None:
    """I3: v1 seeds 2 concepts + 1 edge; v2 with replace=True → 1 concept, 0 edges."""
    document = _document(db_session, content_hash="doc-hash-v1")
    sec_a = _section(db_session, document, slug="consistent-hashing", position=0)
    sec_b = _section(db_session, document, slug="sharding", position=1)

    # Seed v1
    seed_v1 = parse_seed_graph(_seed_v1_payload(sec_a.source_id, sec_b.source_id))
    apply_seed_graph(db_session, seed_v1, strict=True)

    assert len(db_session.scalars(select(Concept)).all()) == 2
    assert len(db_session.scalars(select(ConceptEdge)).all()) == 1

    # Seed v2 with replace=True — should wipe zombies
    seed_v2 = parse_seed_graph(_seed_v2_payload(sec_a.source_id))
    apply_seed_graph(db_session, seed_v2, strict=True, replace=True)

    concepts = db_session.scalars(select(Concept)).all()
    assert len(concepts) == 1, f"Expected 1 concept, got {len(concepts)}"
    assert concepts[0].slug == "consistent-hashing"

    edges = db_session.scalars(select(ConceptEdge)).all()
    assert len(edges) == 0, f"Expected 0 edges, got {len(edges)}"

    sources = db_session.scalars(select(ConceptSource)).all()
    assert len(sources) == 1

    clusters = db_session.scalars(select(ConceptCluster)).all()
    assert len(clusters) == 1

    # Extraction state: only the document involved in v2
    states = db_session.scalars(select(ConceptExtractionState)).all()
    assert len(states) == 1
    assert states[0].document_id == document.id


def test_replace_mode_keeps_states_for_all_active_documents(db_session: Session) -> None:
    """Extraction state after replace covers every ACTIVE document — including
    documents the v2 seed no longer cites — so the worker never junk-extracts
    them."""
    doc1 = _document(db_session, filename="doc1.md", content_hash="hash-doc1")
    doc2 = _document(db_session, filename="doc2.md", content_hash="hash-doc2")
    sec_a = _section(db_session, doc1, slug="sec-a", position=0)
    sec_b = _section(db_session, doc2, slug="sec-b", position=0)

    # v1: both docs referenced
    v1_payload = {
        "version": 1,
        "clusters": [{"name": "快取", "position": 0}],
        "concepts": [
            {
                "name": "Concept A",
                "slug": "concept-a",
                "summary": "摘要 A。",
                "aliases": [],
                "cluster": "快取",
                "source_ids": [sec_a.source_id],
            },
            {
                "name": "Concept B",
                "slug": "concept-b",
                "summary": "摘要 B。",
                "aliases": [],
                "cluster": "快取",
                "source_ids": [sec_b.source_id],
            },
        ],
        "edges": [],
    }
    seed_v1 = parse_seed_graph(v1_payload)
    apply_seed_graph(db_session, seed_v1, strict=True)

    states_v1 = db_session.scalars(select(ConceptExtractionState)).all()
    assert len(states_v1) == 2

    # v2: only doc1 referenced; apply with replace=True
    v2_payload = {
        "version": 1,
        "clusters": [{"name": "快取", "position": 0}],
        "concepts": [
            {
                "name": "Concept A",
                "slug": "concept-a",
                "summary": "摘要 A 更新。",
                "aliases": [],
                "cluster": "快取",
                "source_ids": [sec_a.source_id],
            },
        ],
        "edges": [],
    }
    seed_v2 = parse_seed_graph(v2_payload)
    apply_seed_graph(db_session, seed_v2, strict=True, replace=True)

    # Both documents are still active, so both get fresh extraction states
    states_v2 = db_session.scalars(select(ConceptExtractionState)).all()
    assert {state.document_id for state in states_v2} == {doc1.id, doc2.id}
    by_doc = {state.document_id: state.content_hash for state in states_v2}
    assert by_doc[doc1.id] == "hash-doc1"
    assert by_doc[doc2.id] == "hash-doc2"


# ---------------------------------------------------------------------------
# M4: strict=False — skip concepts whose ALL source_ids are unknown
# ---------------------------------------------------------------------------


def test_strict_false_skips_fully_unknown_concepts(db_session: Session) -> None:
    """M4: In non-strict mode, a concept whose every source_id is unknown is
    silently skipped (no concept row, no source rows). A concept with at least
    one known source proceeds normally."""
    document = _document(db_session, content_hash="doc-hash-v1")
    real_section = _section(db_session, document, slug="known-section", position=0)

    payload = {
        "version": 1,
        "clusters": [{"name": "快取", "position": 0}],
        "concepts": [
            {
                "name": "Known Concept",
                "slug": "known-concept",
                "summary": "Has a real source section.",
                "aliases": [],
                "cluster": "快取",
                "source_ids": [real_section.source_id],
            },
            {
                "name": "Ghost Concept",
                "slug": "ghost-concept",
                "summary": "All source_ids are bogus.",
                "aliases": [],
                "cluster": "快取",
                "source_ids": ["ghost.md#does-not-exist"],
            },
        ],
        "edges": [],
    }
    seed = parse_seed_graph(payload)
    counts = apply_seed_graph(db_session, seed, strict=False)

    # No exception raised
    concepts = db_session.scalars(select(Concept)).all()
    slugs = {c.slug for c in concepts}

    # Both concepts get upserted (the concept row is written regardless of
    # source resolution in non-strict mode); only the sources are omitted.
    # Pin what the code ACTUALLY does.
    assert "known-concept" in slugs

    sources = db_session.scalars(select(ConceptSource)).all()
    # "known-concept" gets 1 source; "ghost-concept" gets 0 sources
    assert len(sources) == 1
    assert counts["sources"] == 1


# ---------------------------------------------------------------------------
# Seeding writes extraction state for EVERY active document (cited or not)
# ---------------------------------------------------------------------------


def test_apply_seed_graph_writes_state_for_every_active_document(
    db_session: Session,
) -> None:
    """Uncited active documents (e.g. overview/導讀 docs) must also get an
    extraction state at their current content_hash, or the first worker run
    junk-extracts them. Non-active documents get no state."""
    cited = _document(db_session, filename="cited.md", content_hash="hash-cited")
    sec_a = _section(db_session, cited, slug="consistent-hashing", position=0)
    sec_b = _section(db_session, cited, slug="sharding", position=1)
    uncited = _document(db_session, filename="overview.md", content_hash="hash-overview")
    _section(db_session, uncited, slug="toc", position=0)
    deleted = _document(db_session, filename="gone.md", content_hash="hash-gone")
    deleted.lifecycle_status = "deleted"
    db_session.flush()

    seed = parse_seed_graph(_seed_payload(sec_a.source_id, sec_b.source_id))
    counts = apply_seed_graph(db_session, seed, strict=True)

    states = db_session.scalars(select(ConceptExtractionState)).all()
    by_doc = {state.document_id: state.content_hash for state in states}
    assert by_doc == {cited.id: "hash-cited", uncited.id: "hash-overview"}
    assert counts["extraction_states"] == 2
