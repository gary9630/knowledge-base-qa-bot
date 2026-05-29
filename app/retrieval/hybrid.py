from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Protocol

from sqlalchemy.orm import Session

from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.models import (
    RetrievalDecision,
    RetrievalDiagnostics,
    RetrievalResult,
    RetrievalStrategy,
    RetrievedCandidate,
    expand_query_terms,
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
        visibility_labels: Sequence[str] | None = ("public",),
        score_threshold: float = 0.10,
    ) -> None:
        if score_threshold < 0.0:
            raise ValueError("score_threshold must be non-negative")

        self.lexical_retriever = lexical_retriever or _build_lexical_retriever(
            session,
            visibility_labels,
        )
        self.vector_retriever = vector_retriever or _build_vector_retriever(
            session,
            embedding_provider,
            visibility_labels,
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
        if strategy not in ("lexical", "markdown", "vector", "hybrid"):
            raise ValueError(f"unsupported retrieval strategy: {strategy}")
        if limit <= 0 or not query.strip():
            return RetrievalResult(
                decision="cannot_confirm",
                candidates=[],
                diagnostics=RetrievalDiagnostics(
                    strategy=strategy,
                    requested_limit=limit,
                    score_threshold=self.score_threshold,
                ),
            )

        normalized_strategy: RetrievalStrategy = "lexical" if strategy == "markdown" else strategy
        candidates: list[RetrievedCandidate] = []
        if normalized_strategy in ("lexical", "hybrid"):
            candidates.extend(self.lexical_retriever.search(query, limit))
        if normalized_strategy in ("vector", "hybrid"):
            candidates.extend(self.vector_retriever.search(query, limit))

        merged = rerank_results_for_query(query, merge_results(candidates))
        accepted = [candidate for candidate in merged if candidate.score >= self.score_threshold][
            :limit
        ]
        rejected = [candidate for candidate in merged if candidate.score < self.score_threshold]
        if strategy == "markdown":
            accepted = [replace(candidate, strategy="markdown") for candidate in accepted]
            rejected = [replace(candidate, strategy="markdown") for candidate in rejected]
        decision: RetrievalDecision = "can_answer" if accepted else "cannot_confirm"
        diagnostics = retrieval_diagnostics(
            strategy=strategy,
            requested_limit=limit,
            score_threshold=self.score_threshold,
            raw_candidates=candidates,
            merged_candidates=merged,
            accepted_candidates=accepted,
            rejected_candidates=rejected,
        )

        return RetrievalResult(
            decision=decision,
            candidates=accepted,
            rejected_candidates=rejected if debug else [],
            diagnostics=diagnostics,
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
        base_score = max(strategy_scores.values(), default=best.score)
        score, priority_debug_scores = _score_with_source_priority(
            base_score,
            best.source_priority,
        )
        debug_scores.update(priority_debug_scores)
        merged.append(
            replace(
                best,
                score=score,
                strategy=strategy,
                debug_scores=debug_scores,
            )
        )

    return sorted(
        merged,
        key=lambda candidate: (-candidate.score, candidate.filename, candidate.source_id),
    )


def rerank_results_for_query(
    query: str,
    candidates: list[RetrievedCandidate],
) -> list[RetrievedCandidate]:
    reranked: list[RetrievedCandidate] = []
    for candidate in candidates:
        boost = _query_relevance_boost(query, candidate)
        if boost <= 0.0:
            reranked.append(candidate)
            continue
        reranked.append(
            replace(
                candidate,
                score=min(1.0, candidate.score + boost),
                debug_scores={
                    **candidate.debug_scores,
                    "base_score": candidate.score,
                    "query_relevance_boost": boost,
                },
            )
        )
    return sorted(
        reranked,
        key=lambda candidate: (-candidate.score, candidate.filename, candidate.source_id),
    )


def _query_relevance_boost(query: str, candidate: RetrievedCandidate) -> float:
    terms = [
        term
        for term in expand_query_terms(query, max_terms=24)
        if _significant_query_term(term)
    ]
    if not terms:
        return 0.0

    haystack = _normalized_candidate_text(candidate)
    boost = 0.0
    for term in terms:
        if _normalize_text(term) not in haystack:
            continue
        boost += min(0.03, len(term) * 0.005)
    return min(0.08, boost)


def _significant_query_term(term: str) -> bool:
    return len(term) >= 3


def _normalized_candidate_text(candidate: RetrievedCandidate) -> str:
    return _normalize_text(
        "\n".join(
            [
                candidate.filename,
                candidate.source_id,
                candidate.heading,
                candidate.body_md,
            ]
        )
    )


def _normalize_text(value: str) -> str:
    return value.casefold()


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


def _score_with_source_priority(
    base_score: float,
    source_priority: int,
) -> tuple[float, dict[str, float]]:
    if source_priority <= 0:
        return base_score, {}

    boost = min(0.05, source_priority * 0.01)
    return min(1.0, base_score + boost), {
        "base_score": base_score,
        "source_priority": float(source_priority),
        "source_priority_boost": boost,
    }


def retrieval_diagnostics(
    *,
    strategy: str,
    requested_limit: int,
    score_threshold: float,
    raw_candidates: list[RetrievedCandidate],
    merged_candidates: list[RetrievedCandidate],
    accepted_candidates: list[RetrievedCandidate],
    rejected_candidates: list[RetrievedCandidate],
) -> RetrievalDiagnostics:
    score_debug_by_source_id: dict[str, dict[str, float]] = {}
    for candidate in merged_candidates:
        score_debug_by_source_id[candidate.source_id] = {
            "score": candidate.score,
            **candidate.debug_scores,
        }

    return RetrievalDiagnostics(
        strategy=strategy,
        requested_limit=requested_limit,
        score_threshold=score_threshold,
        raw_candidate_count=len(raw_candidates),
        merged_candidate_count=len(merged_candidates),
        accepted_count=len(accepted_candidates),
        rejected_count=len(rejected_candidates),
        top_score=accepted_candidates[0].score if accepted_candidates else None,
        selected_source_ids=tuple(candidate.source_id for candidate in accepted_candidates),
        rejected_source_ids=tuple(candidate.source_id for candidate in rejected_candidates),
        strategy_counts=_strategy_counts(raw_candidates),
        score_debug_by_source_id=score_debug_by_source_id,
    )


def _strategy_counts(candidates: list[RetrievedCandidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.strategy] = counts.get(candidate.strategy, 0) + 1
    return counts


def _build_lexical_retriever(
    session: Session | None,
    visibility_labels: Sequence[str] | None,
) -> LexicalRetriever:
    if session is None:
        raise ValueError("session is required when lexical_retriever is not provided")
    return LexicalRetriever(session=session, visibility_labels=visibility_labels)


def _build_vector_retriever(
    session: Session | None,
    embedding_provider: EmbeddingProvider | None,
    visibility_labels: Sequence[str] | None,
) -> VectorRetriever:
    if session is None:
        raise ValueError("session is required when vector_retriever is not provided")
    if embedding_provider is None:
        raise ValueError("embedding_provider is required when vector_retriever is not provided")
    return VectorRetriever(
        session=session,
        embedding_provider=embedding_provider,
        visibility_labels=visibility_labels,
    )
