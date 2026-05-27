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
from app.retrieval.models import RetrievalDecision, RetrievalStrategy, RetrievedCandidate
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


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    strategy: RetrievalStrategy = "hybrid"
    limit: int = Field(default=5, ge=1, le=20)
    debug: bool = False


class SearchResponse(BaseModel):
    decision: RetrievalDecision
    candidates: list[CandidateResponse]
    rejected_candidates: list[CandidateResponse] = Field(default_factory=list)


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
