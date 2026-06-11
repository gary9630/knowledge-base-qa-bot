from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.background_jobs.service import TASK_CONCEPT_EXTRACTION, BackgroundJobService
from app.core.config import Settings
from app.main import create_app
from app.models.tables import (
    Concept,
    ConceptCluster,
    ConceptEdge,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_factory(db_session: Session) -> Callable[[], Session]:
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return create_session


def _app(db_session: Session, *, admin_api_key: str | None = None) -> FastAPI:
    return create_app(
        settings=Settings(
            embedding_provider="fake",
            answer_provider="fake",
            admin_api_key=admin_api_key,
        ),
        session_factory=_session_factory(db_session),
    )


def _seed_document(
    db_session: Session,
    *,
    filename: str = "course.md",
    visibility: list[str] | None = None,
) -> tuple[Document, Section, Section]:
    doc = Document(
        filename=filename,
        canonical_path=f"docs/{filename}",
        source_type="markdown",
        content_hash=f"hash-{filename}",
        visibility=visibility or ["public"],
    )
    s1 = Section(
        document=doc,
        source_id=f"{filename}#intro",
        heading="Introduction",
        heading_slug="intro",
        level=2,
        body_md="Intro body.",
        token_count=3,
        content_hash=f"{filename}-intro",
        position=0,
    )
    s2 = Section(
        document=doc,
        source_id=f"{filename}#detail",
        heading="Detail",
        heading_slug="detail",
        level=2,
        body_md="Detail body.",
        token_count=3,
        content_hash=f"{filename}-detail",
        position=1,
    )
    db_session.add_all([doc, s1, s2])
    db_session.flush()
    return doc, s1, s2


def _seed_graph(
    db_session: Session,
    doc: Document,
    s1: Section,
    s2: Section,
) -> tuple[ConceptCluster, Concept, Concept, ConceptEdge]:
    cluster = ConceptCluster(name="快取", position=0)
    db_session.add(cluster)
    db_session.flush()

    c1 = Concept(
        name="Caching",
        slug="caching",
        summary="儲存計算結果以加速存取。",
        cluster_id=cluster.id,
        aliases=["快取"],
    )
    c2 = Concept(
        name="TTL",
        slug="ttl",
        summary="快取項目的存活時間。",
        cluster_id=cluster.id,
        aliases=[],
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    db_session.add(ConceptSource(concept_id=c1.id, section_id=s1.id))
    db_session.add(ConceptSource(concept_id=c1.id, section_id=s2.id))
    db_session.add(ConceptSource(concept_id=c2.id, section_id=s1.id))

    edge = ConceptEdge(
        source_concept_id=c1.id,
        target_concept_id=c2.id,
        kind="prerequisite",
    )
    db_session.add(edge)
    db_session.flush()
    return cluster, c1, c2, edge


# ---------------------------------------------------------------------------
# Tests: GET /graph
# ---------------------------------------------------------------------------


def test_graph_returns_correct_shape(db_session: Session) -> None:
    doc, s1, s2 = _seed_document(db_session)
    cluster, c1, c2, edge = _seed_graph(db_session, doc, s1, s2)
    db_session.add(
        ConceptExtractionState(document_id=doc.id, content_hash=doc.content_hash)
    )
    db_session.flush()

    client = TestClient(_app(db_session))
    response = client.get("/graph")

    assert response.status_code == 200
    body = response.json()

    # clusters list
    assert len(body["clusters"]) == 1
    c = body["clusters"][0]
    assert c["id"] == str(cluster.id)
    assert c["name"] == "快取"
    assert c["position"] == 0

    # nodes list
    node_ids = {n["id"] for n in body["nodes"]}
    assert str(c1.id) in node_ids
    assert str(c2.id) in node_ids
    node_c1 = next(n for n in body["nodes"] if n["id"] == str(c1.id))
    assert node_c1["name"] == "Caching"
    assert node_c1["slug"] == "caching"
    assert node_c1["summary"] == "儲存計算結果以加速存取。"
    assert node_c1["cluster_id"] == str(cluster.id)
    assert node_c1["aliases"] == ["快取"]  # UI search matches name OR alias
    # c1 has 2 visible sources (s1, s2), both in same public document
    assert node_c1["source_count"] == 2

    node_c2 = next(n for n in body["nodes"] if n["id"] == str(c2.id))
    assert node_c2["source_count"] == 1
    assert node_c2["aliases"] == []

    # edges list — both endpoints visible
    assert len(body["edges"]) == 1
    e = body["edges"][0]
    assert e["source"] == str(c1.id)
    assert e["target"] == str(c2.id)
    assert e["kind"] == "prerequisite"

    # stats
    stats = body["stats"]
    assert stats["concept_count"] == 2
    assert stats["cluster_count"] == 1
    assert stats["edge_count"] == 1
    assert stats["extracted_at"] is not None


def test_graph_empty_when_no_data(db_session: Session) -> None:
    client = TestClient(_app(db_session))
    response = client.get("/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["clusters"] == []
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["stats"]["concept_count"] == 0
    assert body["stats"]["cluster_count"] == 0
    assert body["stats"]["edge_count"] == 0
    assert body["stats"]["extracted_at"] is None


def test_graph_hides_concept_whose_sources_are_in_restricted_document(
    db_session: Session,
) -> None:
    # public doc with a concept
    pub_doc, pub_s1, pub_s2 = _seed_document(db_session, filename="public.md")
    cluster, pub_c, _, edge = _seed_graph(db_session, pub_doc, pub_s1, pub_s2)

    # cohort-only doc with a concept that has an edge back to pub_c
    priv_doc, priv_s1, priv_s2 = _seed_document(
        db_session, filename="private.md", visibility=["cohort-x"]
    )
    hidden_c = Concept(
        name="HiddenConcept",
        slug="hidden-concept",
        summary="不可見的概念。",
        cluster_id=cluster.id,
    )
    db_session.add(hidden_c)
    db_session.flush()
    db_session.add(ConceptSource(concept_id=hidden_c.id, section_id=priv_s1.id))
    # Edge from pub_c -> hidden_c; should be excluded because hidden_c is invisible
    hidden_edge = ConceptEdge(
        source_concept_id=pub_c.id,
        target_concept_id=hidden_c.id,
        kind="related",
    )
    db_session.add(hidden_edge)
    db_session.flush()

    client = TestClient(_app(db_session))
    response = client.get("/graph")

    assert response.status_code == 200
    body = response.json()

    node_ids = {n["id"] for n in body["nodes"]}
    assert str(hidden_c.id) not in node_ids, "hidden concept should not appear for public principal"

    edge_pairs = {(e["source"], e["target"]) for e in body["edges"]}
    assert (str(pub_c.id), str(hidden_c.id)) not in edge_pairs, (
        "edge involving hidden concept should be excluded"
    )


def test_graph_excludes_cluster_with_no_visible_concepts(
    db_session: Session,
) -> None:
    priv_doc, priv_s1, _ = _seed_document(
        db_session, filename="private.md", visibility=["cohort-x"]
    )
    invisible_cluster = ConceptCluster(name="隱藏叢集", position=5)
    db_session.add(invisible_cluster)
    db_session.flush()
    invisible_c = Concept(
        name="InvisibleOnly",
        slug="invisible-only",
        summary="只有私有文件的概念。",
        cluster_id=invisible_cluster.id,
    )
    db_session.add(invisible_c)
    db_session.flush()
    db_session.add(ConceptSource(concept_id=invisible_c.id, section_id=priv_s1.id))
    db_session.flush()

    client = TestClient(_app(db_session))
    response = client.get("/graph")

    cluster_ids = {c["id"] for c in response.json()["clusters"]}
    assert str(invisible_cluster.id) not in cluster_ids


def test_graph_mixed_visibility_source_count(db_session: Session) -> None:
    """A concept with sources in both a public and a restricted document should
    show source_count == 2 (public only) on /graph, and the detail endpoint
    should list exactly those 2 public sources in filename+position order."""
    # Two public sections in "alpha.md"
    pub_doc, pub_s1, pub_s2 = _seed_document(db_session, filename="alpha.md")
    # One restricted section in "zeta.md" (cohort-x)
    priv_doc, priv_s1, _ = _seed_document(
        db_session, filename="zeta.md", visibility=["cohort-x"]
    )

    mixed_c = Concept(
        name="MixedConcept",
        slug="mixed-concept",
        summary="混合可見性的概念。",
    )
    db_session.add(mixed_c)
    db_session.flush()

    # 2 public sources + 1 restricted source
    db_session.add(ConceptSource(concept_id=mixed_c.id, section_id=pub_s1.id))
    db_session.add(ConceptSource(concept_id=mixed_c.id, section_id=pub_s2.id))
    db_session.add(ConceptSource(concept_id=mixed_c.id, section_id=priv_s1.id))
    db_session.flush()

    client = TestClient(_app(db_session))

    # /graph: source_count reflects only public sources
    graph_resp = client.get("/graph")
    assert graph_resp.status_code == 200
    nodes = graph_resp.json()["nodes"]
    mixed_node = next((n for n in nodes if n["id"] == str(mixed_c.id)), None)
    assert mixed_node is not None, "mixed-visibility concept should appear in /graph"
    assert mixed_node["source_count"] == 2

    # /graph/concepts/{id}: exactly the 2 public sources, ordered by filename then position
    detail_resp = client.get(f"/graph/concepts/{mixed_c.id}")
    assert detail_resp.status_code == 200
    sources = detail_resp.json()["sources"]
    source_ids = [s["source_id"] for s in sources]
    # pub_s1 (position=0) comes before pub_s2 (position=1); both in alpha.md
    assert source_ids == [pub_s1.source_id, pub_s2.source_id]
    # Restricted source must not appear
    assert priv_s1.source_id not in source_ids


# ---------------------------------------------------------------------------
# Tests: GET /graph/concepts/{id}
# ---------------------------------------------------------------------------


def test_graph_concept_detail_returns_correct_shape(db_session: Session) -> None:
    doc, s1, s2 = _seed_document(db_session)
    cluster, c1, c2, _ = _seed_graph(db_session, doc, s1, s2)

    client = TestClient(_app(db_session))
    response = client.get(f"/graph/concepts/{c1.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(c1.id)
    assert body["name"] == "Caching"
    assert body["summary"] == "儲存計算結果以加速存取。"
    assert body["aliases"] == ["快取"]
    assert body["cluster"] == "快取"

    # sources ordered by (filename asc, section position asc) — assert exact order
    section_ids = [s["section_id"] for s in body["sources"]]
    assert section_ids == [str(s1.id), str(s2.id)], (
        "sources must be ordered by filename then position; s1 (position=0) before s2 (position=1)"
    )
    # Check required fields present
    for src in body["sources"]:
        assert "section_id" in src
        assert "document_id" in src
        assert "source_id" in src
        assert "filename" in src
        assert "heading" in src


def test_graph_concept_detail_no_cluster(db_session: Session) -> None:
    doc, s1, _ = _seed_document(db_session)
    c = Concept(name="Standalone", slug="standalone", summary="無叢集概念。")
    db_session.add(c)
    db_session.flush()
    db_session.add(ConceptSource(concept_id=c.id, section_id=s1.id))
    db_session.flush()

    client = TestClient(_app(db_session))
    response = client.get(f"/graph/concepts/{c.id}")

    assert response.status_code == 200
    assert response.json()["cluster"] is None


def test_graph_concept_detail_404_for_unknown_id(db_session: Session) -> None:
    client = TestClient(_app(db_session))
    response = client.get("/graph/concepts/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404


def test_graph_concept_detail_404_for_hidden_concept(db_session: Session) -> None:
    """A concept whose only sources are in a non-public document is 404."""
    priv_doc, priv_s1, _ = _seed_document(
        db_session, filename="private.md", visibility=["cohort-x"]
    )
    hidden_c = Concept(
        name="HiddenDetail",
        slug="hidden-detail",
        summary="私有。",
    )
    db_session.add(hidden_c)
    db_session.flush()
    db_session.add(ConceptSource(concept_id=hidden_c.id, section_id=priv_s1.id))
    db_session.flush()

    client = TestClient(_app(db_session))
    response = client.get(f"/graph/concepts/{hidden_c.id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests: POST /graph/extract (admin trigger)
# ---------------------------------------------------------------------------


def test_graph_extract_without_admin_key_is_rejected(db_session: Session) -> None:
    # admin_api_key configured → missing key → 401
    client = TestClient(_app(db_session, admin_api_key="secret"))
    response = client.post("/graph/extract")
    assert response.status_code == 401


def test_graph_extract_with_wrong_admin_key_is_rejected(db_session: Session) -> None:
    client = TestClient(_app(db_session, admin_api_key="secret"))
    response = client.post(
        "/graph/extract", headers={"X-KB-Admin-Key": "wrong"}
    )
    assert response.status_code == 401


def test_graph_extract_with_valid_admin_key_returns_202_and_enqueues_job(
    db_session: Session,
) -> None:
    client = TestClient(_app(db_session, admin_api_key="secret"))
    response = client.post(
        "/graph/extract", headers={"X-KB-Admin-Key": "secret"}
    )

    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body

    job_id = UUID(body["job_id"])
    job = BackgroundJobService(db_session).get(job_id)
    assert job is not None
    assert job.task_type == TASK_CONCEPT_EXTRACTION
    assert job.payload_json.get("reason") == "manual"


def test_graph_extract_in_dev_mode_without_key_returns_202(db_session: Session) -> None:
    """In development (no admin_api_key configured, non-production env), admin
    access is granted without a key."""
    client = TestClient(
        _app(db_session, admin_api_key=None)  # default dev behaviour
    )
    response = client.post("/graph/extract")
    assert response.status_code == 202
