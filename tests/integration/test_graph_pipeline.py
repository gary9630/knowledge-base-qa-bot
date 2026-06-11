from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.pipeline import GraphExtractionPipeline
from app.models.tables import (
    Concept,
    ConceptEdge,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)


class ScriptedCaller:
    """Returns responses keyed by system-prompt kind, in order per kind."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.responses: dict[str, list[str]] = {}

    def queue(self, system_contains: str, response: str) -> None:
        self.responses.setdefault(system_contains, []).append(response)

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        for key, queued in self.responses.items():
            if key in system and queued:
                return queued.pop(0)
        return "{}"


def _seed_document(
    db_session: Session, *, filename: str, slugs: list[str], content_hash: str
) -> Document:
    document = Document(
        filename=filename,
        canonical_path=f"/docs/{filename}",
        source_type="markdown",
        content_hash=content_hash,
    )
    db_session.add(document)
    db_session.flush()
    for position, slug in enumerate(slugs):
        db_session.add(
            Section(
                document_id=document.id,
                source_id=f"{filename}#{slug}",
                heading=slug,
                heading_slug=slug,
                level=2,
                body_md=f"{slug} 的內容。",
                token_count=8,
                content_hash=f"{filename}-{slug}",
                position=position,
            )
        )
    db_session.flush()
    return document


def _document_response(filename: str, names: list[str], slugs: list[str]) -> str:
    return json.dumps(
        {
            "concepts": [
                {"name": name, "summary": f"{name} 摘要。", "source_ids": [f"{filename}#{slug}"]}
                for name, slug in zip(names, slugs, strict=True)
            ],
            "edges": (
                [{"source": names[0], "target": names[1], "kind": "prerequisite"}]
                if len(names) > 1
                else []
            ),
        }
    )


def test_pipeline_extracts_merges_and_clusters(db_session: Session) -> None:
    _seed_document(db_session, filename="a.md", slugs=["s1", "s2"], content_hash="ha")
    caller = ScriptedCaller()
    caller.queue(
        "extract a concept graph",
        _document_response("a.md", ["Caching", "TTL"], ["s1", "s2"]),
    )
    caller.queue("deduplicate concept names", json.dumps({"merges": []}))
    caller.queue(
        "group course concepts",
        json.dumps({"clusters": [{"name": "快取", "concepts": ["Caching", "TTL"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    pipeline = GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    )
    stats = pipeline.run()

    concepts = db_session.scalars(select(Concept)).all()
    assert {concept.name for concept in concepts} == {"Caching", "TTL"}
    assert all(
        concept.cluster is not None and concept.cluster.name == "快取" for concept in concepts
    )
    edges = db_session.scalars(select(ConceptEdge)).all()
    assert len(edges) == 1 and edges[0].kind == "prerequisite"
    assert db_session.scalars(select(ConceptSource)).all()
    assert stats["documents_extracted"] == 1


def test_pipeline_is_incremental(db_session: Session) -> None:
    document = _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    db_session.add(ConceptExtractionState(document_id=document.id, content_hash="ha"))
    db_session.flush()

    caller = ScriptedCaller()  # no responses queued: any LLM call would return "{}"
    pipeline = GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    )
    stats = pipeline.run()

    assert stats["documents_extracted"] == 0
    assert caller.calls == []  # nothing to do, no LLM calls at all


def test_pipeline_reextracts_changed_document_and_prunes_orphans(db_session: Session) -> None:
    document = _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha-v2")
    db_session.add(ConceptExtractionState(document_id=document.id, content_hash="ha-v1"))
    # pre-existing concept that the new extraction no longer mentions, sourced only
    # from this document
    stale = Concept(name="Old Idea", slug="old-idea", summary="舊概念。")
    db_session.add(stale)
    db_session.flush()
    section = db_session.scalars(select(Section)).one()
    db_session.add(ConceptSource(concept_id=stale.id, section_id=section.id))
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue("extract a concept graph", _document_response("a.md", ["Fresh"], ["s1"]))
    caller.queue("deduplicate concept names", json.dumps({"merges": []}))
    caller.queue(
        "group course concepts",
        json.dumps({"clusters": [{"name": "主題", "concepts": ["Fresh"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    names = {concept.name for concept in db_session.scalars(select(Concept)).all()}
    assert names == {"Fresh"}  # stale concept lost its only source and was pruned
    state = db_session.scalar(select(ConceptExtractionState))
    assert state is not None and state.content_hash == "ha-v2"


def test_pipeline_merges_into_existing_concepts(db_session: Session) -> None:
    _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    existing = Concept(name="Consistent Hashing", slug="consistent-hashing", summary="既有。")
    db_session.add(existing)
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue(
        "extract a concept graph",
        _document_response("a.md", ["一致性雜湊"], ["s1"]),
    )
    caller.queue(
        "deduplicate concept names",
        json.dumps({"merges": [{"from": "一致性雜湊", "into": "Consistent Hashing"}]}),
    )
    caller.queue(
        "group course concepts",
        json.dumps({"clusters": [{"name": "主題", "concepts": ["Consistent Hashing"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    concepts = db_session.scalars(select(Concept)).all()
    assert len(concepts) == 1
    assert concepts[0].slug == "consistent-hashing"
    assert "一致性雜湊" in concepts[0].aliases
    assert db_session.scalars(select(ConceptSource)).all()  # sources remapped
