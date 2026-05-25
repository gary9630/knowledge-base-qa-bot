from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Protocol

from sqlalchemy.orm import Session

from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.models import (
    RetrievalDecision,
    RetrievalResult,
    RetrievalStrategy,
    RetrievedCandidate,
)
from app.retrieval.vector import VectorRetriever


class Retriever(Protocol):
    def search(self, query: str, limit: int) -> list[RetrievedCandidate]: ...


class HybridRetriever:
    def __init__(
        self,
        *,
        session: Session | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        lexical_retriever: Retriever | None = None,
        vector_retriever: Retriever | None = None,
        score_threshold: float = 0.10,
    ) -> None:
        if score_threshold < 0.0:
            raise ValueError("score_threshold must be non-negative")

        self.lexical_retriever = lexical_retriever or _build_lexical_retriever(session)
        self.vector_retriever = vector_retriever or _build_vector_retriever(
            session,
            embedding_provider,
        )
        self.score_threshold = score_threshold

    def search(
        self,
        query: str,
        *,
        strategy: RetrievalStrategy = "hybrid",
        limit: int = 5,
        debug: bool = False,
    ) -> RetrievalResult:
        if strategy not in ("lexical", "vector", "hybrid"):
            raise ValueError(f"unsupported retrieval strategy: {strategy}")
        if limit <= 0 or not query.strip():
            return RetrievalResult(decision="cannot_confirm", candidates=[])

        candidates: list[RetrievedCandidate] = []
        if strategy in ("lexical", "hybrid"):
            candidates.extend(self.lexical_retriever.search(query, limit))
        if strategy in ("vector", "hybrid"):
            candidates.extend(self.vector_retriever.search(query, limit))

        merged = merge_results(candidates)
        accepted = [candidate for candidate in merged if candidate.score >= self.score_threshold][
            :limit
        ]
        rejected = [candidate for candidate in merged if candidate.score < self.score_threshold]
        decision: RetrievalDecision = "can_answer" if accepted else "cannot_confirm"

        return RetrievalResult(
            decision=decision,
            candidates=accepted,
            rejected_candidates=rejected if debug else [],
        )


def merge_results(candidates: Iterable[RetrievedCandidate]) -> list[RetrievedCandidate]:
    grouped: dict[str, list[RetrievedCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(str(candidate.section_id), []).append(candidate)

    merged: list[RetrievedCandidate] = []
    for group in grouped.values():
        best = max(group, key=lambda candidate: candidate.score)
        strategy_scores = _strategy_scores(group)
        debug_scores = _merged_debug_scores(group, strategy_scores)
        strategy = "hybrid" if len(strategy_scores) > 1 else best.strategy
        merged.append(
            replace(
                best,
                score=max(strategy_scores.values(), default=best.score),
                strategy=strategy,
                debug_scores=debug_scores,
            )
        )

    return sorted(
        merged,
        key=lambda candidate: (-candidate.score, candidate.filename, candidate.source_id),
    )


def _strategy_scores(candidates: list[RetrievedCandidate]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for candidate in candidates:
        key = f"{candidate.strategy}_score"
        scores[key] = max(scores.get(key, 0.0), candidate.score)
    return scores


def _merged_debug_scores(
    candidates: list[RetrievedCandidate],
    strategy_scores: dict[str, float],
) -> dict[str, float]:
    debug_scores = dict(strategy_scores)
    for candidate in candidates:
        for key, value in candidate.debug_scores.items():
            debug_scores[key] = max(debug_scores.get(key, value), value)
    return debug_scores


def _build_lexical_retriever(session: Session | None) -> LexicalRetriever:
    if session is None:
        raise ValueError("session is required when lexical_retriever is not provided")
    return LexicalRetriever(session=session)


def _build_vector_retriever(
    session: Session | None,
    embedding_provider: EmbeddingProvider | None,
) -> VectorRetriever:
    if session is None:
        raise ValueError("session is required when vector_retriever is not provided")
    if embedding_provider is None:
        raise ValueError("embedding_provider is required when vector_retriever is not provided")
    return VectorRetriever(session=session, embedding_provider=embedding_provider)
