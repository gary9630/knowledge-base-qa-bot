from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_embedding_provider,
    get_request_db_session,
    get_source_principal,
)
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.models import (
    RetrievalDecision,
    RetrievalDiagnostics,
    RetrievalStrategy,
    RetrievedCandidate,
)
from app.source_access import SourcePrincipal, visibility_labels_for_principal

router = APIRouter()

API_RETRIEVAL_SCORE_THRESHOLD = 0.05


class CandidateResponse(BaseModel):
    section_id: UUID
    source_id: str
    filename: str
    heading: str
    body_md: str
    score: float
    strategy: str
    source_type: str
    source_priority: int
    debug_scores: dict[str, float] = Field(default_factory=dict)


class RetrievalDiagnosticsResponse(BaseModel):
    strategy: str
    requested_limit: int
    score_threshold: float
    raw_candidate_count: int
    merged_candidate_count: int
    accepted_count: int
    rejected_count: int
    top_score: float | None
    selected_source_ids: list[str] = Field(default_factory=list)
    rejected_source_ids: list[str] = Field(default_factory=list)
    strategy_counts: dict[str, int] = Field(default_factory=dict)
    score_debug_by_source_id: dict[str, dict[str, float]] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    strategy: RetrievalStrategy = "hybrid"
    limit: int = Field(default=5, ge=1, le=20)
    debug: bool = False


class SearchResponse(BaseModel):
    decision: RetrievalDecision
    candidates: list[CandidateResponse]
    rejected_candidates: list[CandidateResponse] = Field(default_factory=list)
    diagnostics: RetrievalDiagnosticsResponse


@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
    principal: Annotated[SourcePrincipal, Depends(get_source_principal)],
) -> SearchResponse:
    retriever = HybridRetriever(
        session=session,
        embedding_provider=get_embedding_provider(request),
        visibility_labels=visibility_labels_for_principal(principal),
        score_threshold=API_RETRIEVAL_SCORE_THRESHOLD,
    )
    result = retriever.search(
        payload.query,
        strategy=payload.strategy,
        limit=payload.limit,
        debug=payload.debug,
    )
    return SearchResponse(
        decision=result.decision,
        candidates=[candidate_response(candidate) for candidate in result.candidates],
        rejected_candidates=[
            candidate_response(candidate) for candidate in result.rejected_candidates
        ],
        diagnostics=retrieval_diagnostics_response(result.diagnostics),
    )


def candidate_response(candidate: RetrievedCandidate) -> CandidateResponse:
    return CandidateResponse(
        section_id=candidate.section_id,
        source_id=candidate.source_id,
        filename=candidate.filename,
        heading=candidate.heading,
        body_md=candidate.body_md,
        score=candidate.score,
        strategy=candidate.strategy,
        source_type=candidate.source_type,
        source_priority=candidate.source_priority,
        debug_scores=dict(candidate.debug_scores),
    )


def retrieval_diagnostics_response(
    diagnostics: RetrievalDiagnostics,
) -> RetrievalDiagnosticsResponse:
    return RetrievalDiagnosticsResponse(
        strategy=diagnostics.strategy,
        requested_limit=diagnostics.requested_limit,
        score_threshold=diagnostics.score_threshold,
        raw_candidate_count=diagnostics.raw_candidate_count,
        merged_candidate_count=diagnostics.merged_candidate_count,
        accepted_count=diagnostics.accepted_count,
        rejected_count=diagnostics.rejected_count,
        top_score=diagnostics.top_score,
        selected_source_ids=list(diagnostics.selected_source_ids),
        rejected_source_ids=list(diagnostics.rejected_source_ids),
        strategy_counts=dict(diagnostics.strategy_counts),
        score_debug_by_source_id={
            source_id: dict(scores)
            for source_id, scores in diagnostics.score_debug_by_source_id.items()
        },
    )
