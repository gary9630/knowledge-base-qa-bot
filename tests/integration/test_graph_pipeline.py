from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.pipeline import GraphExtractionPipeline
from app.models.tables import (
    Concept,
    ConceptCluster,
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

    def queued_total(self) -> int:
        return sum(len(queued) for queued in self.responses.values())

    def call_kinds(self) -> list[str]:
        markers = {
            "extract a concept graph": "extract",
            "deduplicate concept names": "merge",
            "assign the given course concepts": "cluster",
            "Propose edges": "cluster-edges",
        }
        return [
            next((kind for marker, kind in markers.items() if marker in system), "unknown")
            for system, _ in self.calls
        ]


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
    # no merge response queued: with no pre-existing concepts the merge call is skipped
    caller.queue(
        "assign the given course concepts",
        json.dumps({"clusters": [{"name": "快取", "concepts": ["Caching", "TTL"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))
    queued = caller.queued_total()

    pipeline = GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    )
    stats = pipeline.run()

    assert caller.call_kinds() == ["extract", "cluster", "cluster-edges"]
    assert len(caller.calls) == queued
    assert caller.queued_total() == 0  # every queued response was consumed

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
        "assign the given course concepts",
        json.dumps({"clusters": [{"name": "主題", "concepts": ["Fresh"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))
    queued = caller.queued_total()

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    # merge runs because the stale concept pre-exists when the new names arrive
    assert caller.call_kinds() == ["extract", "merge", "cluster", "cluster-edges"]
    assert len(caller.calls) == queued
    assert caller.queued_total() == 0  # every queued response was consumed

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
        "assign the given course concepts",
        json.dumps({"clusters": [{"name": "主題", "concepts": ["Consistent Hashing"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))
    queued = caller.queued_total()

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    assert caller.call_kinds() == ["extract", "merge", "cluster", "cluster-edges"]
    assert len(caller.calls) == queued
    assert caller.queued_total() == 0  # every queued response was consumed

    concepts = db_session.scalars(select(Concept)).all()
    assert len(concepts) == 1
    assert concepts[0].slug == "consistent-hashing"
    assert "一致性雜湊" in concepts[0].aliases
    assert db_session.scalars(select(ConceptSource)).all()  # sources remapped


def test_pipeline_deterministically_merges_alias_match_without_llm(
    db_session: Session,
) -> None:
    """An extracted name equal to an existing concept's alias merges without the
    LLM merge call, even though the slugs differ."""
    _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    cluster = ConceptCluster(name="快取", position=0)
    db_session.add(cluster)
    db_session.flush()
    curated = Concept(
        name="Cache Eviction Policy",
        slug="cache-eviction-policy",
        summary="快取淘汰策略。",
        aliases=["TTL"],
        origin="seed",
        cluster_id=cluster.id,
    )
    db_session.add(curated)
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue(
        "extract a concept graph",
        _document_response("a.md", ["TTL"], ["s1"]),
    )
    # no merge response queued: the alias match resolves the only new name
    # deterministically, so the LLM merge call must be skipped entirely
    queued = caller.queued_total()

    stats = GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    assert caller.call_kinds() == ["extract"]
    assert len(caller.calls) == queued

    concepts = db_session.scalars(select(Concept)).all()
    assert len(concepts) == 1  # no new concept row for the duplicate
    assert concepts[0].slug == "cache-eviction-policy"
    assert concepts[0].aliases == ["TTL"]  # already an alias; not duplicated
    assert concepts[0].summary == "快取淘汰策略。"  # curated summary untouched
    sources = db_session.scalars(select(ConceptSource)).all()
    assert {source.concept_id for source in sources} == {curated.id}
    assert stats["concepts_merged"] == 1
    assert stats["concepts_created"] == 0


def test_pipeline_deterministically_merges_casefolded_name_match(
    db_session: Session,
) -> None:
    """An extracted name equal (casefolded) to an existing concept's name merges
    deterministically; the differing surface form becomes an alias."""
    _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    existing = Concept(
        name="Load Balancing",
        slug="load-balancer",  # curated slug differs from slugify(name)
        summary="負載平衡。",
        origin="seed",
    )
    db_session.add(existing)
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue(
        "extract a concept graph",
        _document_response("a.md", ["load balancing"], ["s1"]),
    )
    caller.queue(
        "assign the given course concepts",
        json.dumps({"clusters": [{"name": "主題", "concepts": ["Load Balancing"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    stats = GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    assert "merge" not in caller.call_kinds()
    concepts = db_session.scalars(select(Concept)).all()
    assert len(concepts) == 1
    assert concepts[0].slug == "load-balancer"
    assert concepts[0].name == "Load Balancing"
    assert concepts[0].aliases == ["load balancing"]  # distinct surface form kept
    sources = db_session.scalars(select(ConceptSource)).all()
    assert {source.concept_id for source in sources} == {existing.id}
    assert stats["concepts_merged"] == 1
    assert stats["concepts_created"] == 0


def test_pipeline_keeps_curated_summary_on_slug_match(db_session: Session) -> None:
    """Re-extraction over a seed-origin concept must not overwrite its curated
    summary; sources are still remapped and aliases still accumulate."""
    _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    curated = Concept(
        name="Caching",
        slug="caching",
        summary="精修的快取摘要。",
        origin="seed",
    )
    db_session.add(curated)
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue(
        "extract a concept graph",
        _document_response("a.md", ["caching"], ["s1"]),
    )
    caller.queue(
        "assign the given course concepts",
        json.dumps({"clusters": [{"name": "快取", "concepts": ["Caching"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    db_session.expire_all()
    concept = db_session.scalar(select(Concept).where(Concept.slug == "caching"))
    assert concept is not None
    assert concept.summary == "精修的快取摘要。"  # curated wording survives
    assert concept.aliases == ["caching"]  # extracted surface form accumulated
    assert db_session.scalars(select(ConceptSource)).all()  # sources remapped


def test_pipeline_updates_summary_on_slug_match_for_extracted_concepts(
    db_session: Session,
) -> None:
    """Non-seed concepts keep refreshing their summary from the latest extraction."""
    _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    extracted = Concept(name="Caching", slug="caching", summary="舊摘要。")
    db_session.add(extracted)
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue(
        "extract a concept graph",
        _document_response("a.md", ["Caching"], ["s1"]),
    )
    caller.queue(
        "assign the given course concepts",
        json.dumps({"clusters": [{"name": "快取", "concepts": ["Caching"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    db_session.expire_all()
    concept = db_session.scalar(select(Concept).where(Concept.slug == "caching"))
    assert concept is not None
    assert concept.summary == "Caching 摘要。"  # refreshed from extraction


def test_pipeline_clusters_only_unclustered_concepts(db_session: Session) -> None:
    # Curated taxonomy: one cluster with an assigned concept, plus an empty
    # cluster. Incremental clustering must touch neither.
    kept_cluster = ConceptCluster(name="既有主題", position=0)
    empty_cluster = ConceptCluster(name="空主題", position=1)
    db_session.add_all([kept_cluster, empty_cluster])
    db_session.flush()
    curated = Concept(
        name="Caching",
        slug="caching",
        summary="既有概念。",
        origin="seed",
        cluster_id=kept_cluster.id,
    )
    db_session.add(curated)
    db_session.flush()

    _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha")
    caller = ScriptedCaller()
    caller.queue("extract a concept graph", _document_response("a.md", ["Fresh"], ["s1"]))
    caller.queue("deduplicate concept names", json.dumps({"merges": []}))
    caller.queue(
        "assign the given course concepts",
        json.dumps({"clusters": [{"name": "新主題", "concepts": ["Fresh"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))
    queued = caller.queued_total()

    GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    assert caller.call_kinds() == ["extract", "merge", "cluster", "cluster-edges"]
    assert len(caller.calls) == queued

    # the cluster call payload contains ONLY the unclustered concept (with its
    # summary) plus the existing cluster names — never the clustered ones
    cluster_payloads = [
        json.loads(user)
        for system, user in caller.calls
        if "assign the given course concepts" in system
    ]
    assert len(cluster_payloads) == 1
    payload = cluster_payloads[0]
    assert [concept["name"] for concept in payload["concepts"]] == ["Fresh"]
    assert all("summary" in concept for concept in payload["concepts"])
    assert set(payload["existing_clusters"]) == {"既有主題", "空主題"}

    db_session.expire_all()
    curated_after = db_session.scalar(select(Concept).where(Concept.slug == "caching"))
    assert curated_after is not None
    assert curated_after.cluster_id == kept_cluster.id  # never reassigned
    fresh = db_session.scalar(select(Concept).where(Concept.slug == "fresh"))
    assert fresh is not None
    assert fresh.cluster is not None and fresh.cluster.name == "新主題"
    cluster_names = {cluster.name for cluster in db_session.scalars(select(ConceptCluster))}
    # the empty curated cluster survives: the pipeline never deletes clusters
    assert cluster_names == {"既有主題", "空主題", "新主題"}


def test_pipeline_preserves_seed_origin_concept_whose_sources_vanish(
    db_session: Session,
) -> None:
    document = _seed_document(db_session, filename="a.md", slugs=["s1"], content_hash="ha-v2")
    db_session.add(ConceptExtractionState(document_id=document.id, content_hash="ha-v1"))
    cluster = ConceptCluster(name="快取", position=0)
    db_session.add(cluster)
    db_session.flush()
    # curated concept sourced only from this document; the re-extraction below
    # no longer cites it
    curated = Concept(
        name="Cache Eviction Policy",
        slug="cache-eviction-policy",
        summary="快取淘汰策略。",
        origin="seed",
        cluster_id=cluster.id,
    )
    db_session.add(curated)
    db_session.flush()
    section = db_session.scalars(select(Section)).one()
    db_session.add(ConceptSource(concept_id=curated.id, section_id=section.id))
    db_session.flush()

    caller = ScriptedCaller()
    caller.queue("extract a concept graph", _document_response("a.md", ["Fresh"], ["s1"]))
    caller.queue("deduplicate concept names", json.dumps({"merges": []}))
    caller.queue(
        "assign the given course concepts",
        json.dumps({"clusters": [{"name": "快取", "concepts": ["Fresh"]}]}),
    )
    caller.queue("Propose edges", json.dumps({"edges": []}))

    stats = GraphExtractionPipeline(
        session=db_session, caller=caller, max_concepts_per_doc=30, token_budget=12000
    ).run()

    # the seed-origin concept survives orphaning (it merely disappears from
    # /graph, which hides zero-visible-source concepts)
    names = {concept.name for concept in db_session.scalars(select(Concept)).all()}
    assert names == {"Cache Eviction Policy", "Fresh"}
    assert stats["concepts_pruned"] == 0
    db_session.expire_all()
    curated_after = db_session.scalar(
        select(Concept).where(Concept.slug == "cache-eviction-policy")
    )
    assert curated_after is not None
    assert curated_after.sources == []  # orphaned but alive
    state = db_session.scalar(select(ConceptExtractionState))
    assert state is not None and state.content_hash == "ha-v2"
