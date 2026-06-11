from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_request_db_session, get_source_principal, require_admin_access
from app.background_jobs.service import TASK_CONCEPT_EXTRACTION, BackgroundJobService
from app.document_lifecycle import active_document_filter
from app.models.tables import (
    Concept,
    ConceptCluster,
    ConceptEdge,
    ConceptExtractionState,
    ConceptSource,
    Document,
    Section,
)
from app.source_access import SourcePrincipal, source_visibility_filter

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class GraphCluster(BaseModel):
    id: UUID
    name: str
    position: int


class GraphNode(BaseModel):
    id: UUID
    name: str
    slug: str
    summary: str
    cluster_id: UUID | None
    source_count: int


class GraphEdge(BaseModel):
    source: UUID
    target: UUID
    kind: str


class GraphStats(BaseModel):
    concept_count: int
    cluster_count: int
    edge_count: int
    extracted_at: datetime | None


class GraphResponse(BaseModel):
    clusters: list[GraphCluster]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: GraphStats


class ConceptSourceDetail(BaseModel):
    section_id: UUID
    document_id: UUID
    source_id: str
    filename: str
    heading: str


class ConceptDetailResponse(BaseModel):
    id: UUID
    name: str
    summary: str
    aliases: list[str]
    cluster: str | None
    sources: list[ConceptSourceDetail]


class ExtractJobResponse(BaseModel):
    job_id: UUID


# ---------------------------------------------------------------------------
# Helper: load visible (concept_id -> {section data, document data}) pairs
# ---------------------------------------------------------------------------


def _load_visible_concept_sources(
    session: Session,
    principal: SourcePrincipal,
) -> dict[UUID, list[tuple[Section, Document]]]:
    """Return mapping concept_id -> list of (section, document) for all visible
    active-document sources.  One query, aggregated in Python."""
    rows = session.execute(
        select(ConceptSource.concept_id, Section, Document)
        .join(Section, Section.id == ConceptSource.section_id)
        .join(Document, Document.id == Section.document_id)
        .where(active_document_filter())
        .where(source_visibility_filter(Document.visibility, principal))
        .order_by(Document.filename.asc(), Section.position.asc(), Section.id.asc())
    ).all()

    result: dict[UUID, list[tuple[Section, Document]]] = {}
    for concept_id, section, document in rows:
        result.setdefault(concept_id, []).append((section, document))
    return result


# ---------------------------------------------------------------------------
# GET /graph
# ---------------------------------------------------------------------------


@router.get("/graph", response_model=GraphResponse)
def get_graph(
    session: Annotated[Session, Depends(get_request_db_session)],
    principal: Annotated[SourcePrincipal, Depends(get_source_principal)],
) -> GraphResponse:
    visible_sources = _load_visible_concept_sources(session, principal)
    visible_concept_ids: set[UUID] = set(visible_sources.keys())

    # Load all concepts (we'll filter by visibility in Python)
    all_concepts = session.scalars(select(Concept)).all()

    nodes: list[GraphNode] = []
    for concept in all_concepts:
        if concept.id not in visible_concept_ids:
            continue
        nodes.append(
            GraphNode(
                id=concept.id,
                name=concept.name,
                slug=concept.slug,
                summary=concept.summary,
                cluster_id=concept.cluster_id,
                source_count=len(visible_sources[concept.id]),
            )
        )

    # Load edges — include only when BOTH endpoints are visible
    all_edges = session.scalars(select(ConceptEdge)).all()
    edges: list[GraphEdge] = []
    for edge in all_edges:
        if (
            edge.source_concept_id in visible_concept_ids
            and edge.target_concept_id in visible_concept_ids
        ):
            edges.append(
                GraphEdge(
                    source=edge.source_concept_id,
                    target=edge.target_concept_id,
                    kind=edge.kind,
                )
            )

    # Clusters — only those containing ≥1 visible concept; ordered by position
    visible_cluster_ids = {
        concept.cluster_id
        for concept in all_concepts
        if concept.id in visible_concept_ids and concept.cluster_id is not None
    }
    all_clusters = session.scalars(
        select(ConceptCluster).order_by(ConceptCluster.position.asc(), ConceptCluster.id.asc())
    ).all()
    clusters: list[GraphCluster] = [
        GraphCluster(id=c.id, name=c.name, position=c.position)
        for c in all_clusters
        if c.id in visible_cluster_ids
    ]

    # extracted_at = max(ConceptExtractionState.updated_at) or None
    extracted_at: datetime | None = session.scalar(
        select(func.max(ConceptExtractionState.updated_at))
    )

    stats = GraphStats(
        concept_count=len(nodes),
        cluster_count=len(clusters),
        edge_count=len(edges),
        extracted_at=extracted_at,
    )
    return GraphResponse(clusters=clusters, nodes=nodes, edges=edges, stats=stats)


# ---------------------------------------------------------------------------
# GET /graph/concepts/{id}
# ---------------------------------------------------------------------------


@router.get("/graph/concepts/{concept_id}", response_model=ConceptDetailResponse)
def get_concept_detail(
    concept_id: UUID,
    session: Annotated[Session, Depends(get_request_db_session)],
    principal: Annotated[SourcePrincipal, Depends(get_source_principal)],
) -> ConceptDetailResponse:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail="Concept not found.")

    # Load visible sources for this concept only
    rows = session.execute(
        select(Section, Document)
        .join(ConceptSource, ConceptSource.section_id == Section.id)
        .join(Document, Document.id == Section.document_id)
        .where(ConceptSource.concept_id == concept_id)
        .where(active_document_filter())
        .where(source_visibility_filter(Document.visibility, principal))
        .order_by(Document.filename.asc(), Section.position.asc(), Section.id.asc())
    ).all()

    # A concept with zero visible sources is 404 (don't leak hidden concepts)
    if not rows:
        raise HTTPException(status_code=404, detail="Concept not found.")

    sources: list[ConceptSourceDetail] = [
        ConceptSourceDetail(
            section_id=section.id,
            document_id=document.id,
            source_id=section.source_id,
            filename=document.filename,
            heading=section.heading,
        )
        for section, document in rows
    ]

    cluster_name: str | None = None
    if concept.cluster_id is not None:
        cluster = session.get(ConceptCluster, concept.cluster_id)
        if cluster is not None:
            cluster_name = cluster.name

    return ConceptDetailResponse(
        id=concept.id,
        name=concept.name,
        summary=concept.summary,
        aliases=list(concept.aliases),
        cluster=cluster_name,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# POST /graph/extract (admin)
# ---------------------------------------------------------------------------


@router.post("/graph/extract", status_code=202, response_model=ExtractJobResponse)
def trigger_extract(
    session: Annotated[Session, Depends(get_request_db_session)],
    _: Annotated[None, Depends(require_admin_access)] = None,
) -> ExtractJobResponse:
    job = BackgroundJobService(session).enqueue(
        task_type=TASK_CONCEPT_EXTRACTION,
        payload={"reason": "manual"},
    )
    session.commit()
    return ExtractJobResponse(job_id=job.id)
