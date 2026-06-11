from __future__ import annotations

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


def _document(db_session: Session) -> Document:
    document = Document(
        filename="course.md",
        canonical_path="/docs/course.md",
        source_type="markdown",
        content_hash="doc-hash",
    )
    db_session.add(document)
    db_session.flush()
    return document


def _section(db_session: Session, document: Document, *, slug: str, position: int) -> Section:
    section = Section(
        document_id=document.id,
        source_id=f"course.md#{slug}",
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


def test_concept_graph_round_trip(db_session: Session) -> None:
    document = _document(db_session)
    section = _section(db_session, document, slug="consistent-hashing", position=0)

    cluster = ConceptCluster(name="快取", position=0)
    db_session.add(cluster)
    db_session.flush()

    concept = Concept(
        name="Consistent Hashing",
        slug="consistent-hashing",
        summary="把節點與鍵映射到同一個雜湊環。",
        cluster_id=cluster.id,
        aliases=["一致性雜湊"],
    )
    other = Concept(name="Sharding", slug="sharding", summary="資料水平切分。")
    db_session.add_all([concept, other])
    db_session.flush()

    db_session.add(
        ConceptEdge(source_concept_id=concept.id, target_concept_id=other.id, kind="related")
    )
    db_session.add(ConceptSource(concept_id=concept.id, section_id=section.id))
    db_session.add(
        ConceptExtractionState(document_id=document.id, content_hash=document.content_hash)
    )
    db_session.flush()

    loaded = db_session.scalar(select(Concept).where(Concept.slug == "consistent-hashing"))
    assert loaded is not None
    assert loaded.cluster_id == cluster.id
    assert loaded.aliases == ["一致性雜湊"]


def test_deleting_section_cascades_concept_sources(db_session: Session) -> None:
    document = _document(db_session)
    section = _section(db_session, document, slug="quorum", position=0)
    concept = Concept(name="Quorum", slug="quorum", summary="多數決讀寫。")
    db_session.add(concept)
    db_session.flush()
    db_session.add(ConceptSource(concept_id=concept.id, section_id=section.id))
    db_session.flush()

    db_session.delete(section)
    db_session.flush()

    remaining = db_session.scalars(select(ConceptSource)).all()
    assert remaining == []


def test_deleting_concept_cascades_edges(db_session: Session) -> None:
    a = Concept(name="A", slug="a", summary="a")
    b = Concept(name="B", slug="b", summary="b")
    db_session.add_all([a, b])
    db_session.flush()
    db_session.add(ConceptEdge(source_concept_id=a.id, target_concept_id=b.id, kind="related"))
    db_session.flush()

    db_session.delete(a)
    db_session.flush()

    assert db_session.scalars(select(ConceptEdge)).all() == []


def test_deleting_cluster_nullifies_concept_cluster_id(db_session: Session) -> None:
    cluster = ConceptCluster(name="測試叢集", position=0)
    db_session.add(cluster)
    db_session.flush()

    concept = Concept(
        name="Orphan",
        slug="orphan",
        summary="概念隸屬於即將被刪除的叢集。",
        cluster_id=cluster.id,
    )
    db_session.add(concept)
    db_session.flush()

    db_session.delete(cluster)
    db_session.flush()

    db_session.refresh(concept)
    assert concept.cluster_id is None
    # concept itself must still exist
    surviving = db_session.scalar(select(Concept).where(Concept.slug == "orphan"))
    assert surviving is not None
