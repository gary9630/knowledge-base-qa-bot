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
