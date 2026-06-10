from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.answer.context_assembly import ContextAssembler
from app.models.tables import Document, Section
from app.retrieval.models import RetrievedCandidate


def _seed_document(db_session: Session, *, section_count: int = 5) -> list[Section]:
    document = Document(
        filename="course.md",
        canonical_path="/docs/course.md",
        source_type="markdown",
        content_hash="hash",
    )
    db_session.add(document)
    db_session.flush()
    sections = []
    for index in range(section_count):
        section = Section(
            document_id=document.id,
            source_id=f"course.md#sec-{index}",
            heading=f"Section {index}",
            heading_slug=f"sec-{index}",
            level=2,
            body_md=f"內容段落 {index}。",
            token_count=10,
            content_hash=f"hash-{index}",
            position=index,
        )
        db_session.add(section)
        sections.append(section)
    db_session.flush()
    return sections


def _hit(section: Section, *, score: float = 0.9) -> RetrievedCandidate:
    return RetrievedCandidate(
        section_id=section.id,
        source_id=section.source_id,
        filename="course.md",
        heading=section.heading,
        body_md="chunk excerpt",
        score=score,
        strategy="hybrid",
    )


def test_assemble_expands_hit_to_full_section_plus_neighbors(db_session: Session) -> None:
    sections = _seed_document(db_session)
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[2])])

    source_ids = [source.source_id for source in assembled.sources]
    assert source_ids == ["course.md#sec-1", "course.md#sec-2", "course.md#sec-3"]
    hit_source = next(source for source in assembled.sources if source.is_hit)
    assert hit_source.body_md == "內容段落 2。"  # full section body, not the chunk excerpt
    assert assembled.diagnostics.hit_count == 1
    assert assembled.diagnostics.neighbor_count == 2


def test_assemble_merges_overlapping_windows(db_session: Session) -> None:
    sections = _seed_document(db_session)
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[1]), _hit(sections[2], score=0.5)])

    source_ids = [source.source_id for source in assembled.sources]
    assert source_ids == [
        "course.md#sec-0",
        "course.md#sec-1",
        "course.md#sec-2",
        "course.md#sec-3",
    ]
    assert sum(1 for source in assembled.sources if source.is_hit) == 2


def test_assemble_without_positions_skips_neighbors(db_session: Session) -> None:
    sections = _seed_document(db_session)
    for section in sections:
        section.position = None
    db_session.flush()
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[2])])

    assert [source.source_id for source in assembled.sources] == ["course.md#sec-2"]
    assert assembled.sources[0].body_md == "內容段落 2。"


def test_assemble_with_zero_neighbor_window_expands_body_only(db_session: Session) -> None:
    sections = _seed_document(db_session)
    assembler = ContextAssembler(session=db_session, neighbor_sections=0, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[2])])

    assert [source.source_id for source in assembled.sources] == ["course.md#sec-2"]
    assert assembled.sources[0].body_md == "內容段落 2。"
    assert assembled.diagnostics.neighbor_count == 0


def test_assemble_missing_section_falls_back_to_candidate(db_session: Session) -> None:
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)
    ghost = RetrievedCandidate(
        section_id=uuid4(),
        source_id="ghost.md#gone",
        filename="ghost.md",
        heading="Gone",
        body_md="cached chunk text",
        score=0.7,
        strategy="vector",
    )

    assembled = assembler.assemble([ghost])

    assert len(assembled.sources) == 1
    assert assembled.sources[0].body_md == "cached chunk text"


def test_assemble_k2_window_returns_all_five_sections_in_reading_order(
    db_session: Session,
) -> None:
    sections = _seed_document(db_session, section_count=5)
    # Hit is at position 2; with neighbor_sections=2 that spans positions 0-4.
    assembler = ContextAssembler(session=db_session, neighbor_sections=2, token_budget=8000)

    assembled = assembler.assemble([_hit(sections[2])])

    source_ids = [source.source_id for source in assembled.sources]
    assert source_ids == [
        "course.md#sec-0",
        "course.md#sec-1",
        "course.md#sec-2",
        "course.md#sec-3",
        "course.md#sec-4",
    ]
    assert assembled.diagnostics.hit_count == 1
    assert assembled.diagnostics.neighbor_count == 4

    # Verify neighbor distances from the hit at position 2.
    distance_by_id = {
        source.source_id: source.neighbor_distance for source in assembled.sources
    }
    assert distance_by_id["course.md#sec-0"] == 2
    assert distance_by_id["course.md#sec-1"] == 1
    assert distance_by_id["course.md#sec-2"] == 0  # the hit itself
    assert distance_by_id["course.md#sec-3"] == 1
    assert distance_by_id["course.md#sec-4"] == 2


def test_assemble_adjacent_hits_preserve_is_hit_flags(db_session: Session) -> None:
    sections = _seed_document(db_session, section_count=4)
    # Hits at positions 1 and 2 with K=1: their windows together cover 0-3.
    assembler = ContextAssembler(session=db_session, neighbor_sections=1, token_budget=8000)

    assembled = assembler.assemble(
        [_hit(sections[1], score=0.9), _hit(sections[2], score=0.7)]
    )

    source_ids = [source.source_id for source in assembled.sources]
    assert source_ids == [
        "course.md#sec-0",
        "course.md#sec-1",
        "course.md#sec-2",
        "course.md#sec-3",
    ]

    is_hit_by_id = {source.source_id: source.is_hit for source in assembled.sources}
    assert is_hit_by_id["course.md#sec-1"] is True
    assert is_hit_by_id["course.md#sec-2"] is True
    assert is_hit_by_id["course.md#sec-0"] is False
    assert is_hit_by_id["course.md#sec-3"] is False

    # The shared neighbor at sec-0 is adjacent to both hits; its anchor_score should
    # come from the higher-scoring hit (0.9, anchored by sections[1]).
    anchor_by_id = {source.source_id: source.score for source in assembled.sources}
    # sec-0 is a neighbor (score is None); verify via diagnostics that both hits are kept.
    assert assembled.diagnostics.hit_count == 2
    assert assembled.diagnostics.neighbor_count == 2
    assert anchor_by_id["course.md#sec-0"] is None  # neighbors carry no retrieval score
