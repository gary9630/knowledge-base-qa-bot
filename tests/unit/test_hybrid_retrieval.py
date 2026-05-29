from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.retrieval.hybrid import HybridRetriever, merge_results
from app.retrieval.models import RetrievedCandidate


class StubRetriever:
    def __init__(self, candidates: list[RetrievedCandidate]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[RetrievedCandidate]:
        self.calls.append((query, limit))
        return self.candidates[:limit]


def test_merge_results_deduplicates_by_section_and_prefers_highest_score() -> None:
    section_id = uuid4()
    lower_score = _candidate(section_id=section_id, score=0.24, strategy="lexical")
    higher_score = _candidate(section_id=section_id, score=0.82, strategy="vector")
    other_section = _candidate(score=0.53, strategy="lexical", heading="Other")

    merged = merge_results([lower_score, higher_score, other_section])

    assert [candidate.section_id for candidate in merged] == [
        section_id,
        other_section.section_id,
    ]
    assert merged[0].score == pytest.approx(0.82)
    assert merged[0].strategy == "hybrid"
    assert merged[0].debug_scores == {
        "lexical_score": pytest.approx(0.24),
        "vector_score": pytest.approx(0.82),
    }


def test_merge_results_applies_source_priority_as_small_ranking_boost() -> None:
    transcript = _candidate(
        score=0.60,
        strategy="lexical",
        heading="Transcript",
        source_type="transcript",
        source_priority=1,
    )
    announcement = _candidate(
        score=0.60,
        strategy="lexical",
        heading="Announcement",
        source_type="announcement",
        source_priority=4,
    )

    merged = merge_results([transcript, announcement])

    assert [candidate.heading for candidate in merged] == ["Announcement", "Transcript"]
    assert merged[0].score == pytest.approx(0.64)
    assert merged[0].debug_scores["source_priority"] == 4.0
    assert merged[0].debug_scores["source_priority_boost"] == pytest.approx(0.04)


def test_hybrid_search_returns_cannot_confirm_below_threshold_without_debug() -> None:
    weak_candidate = _candidate(score=0.19, strategy="lexical")
    retriever = HybridRetriever(
        lexical_retriever=StubRetriever([weak_candidate]),
        vector_retriever=StubRetriever([]),
        score_threshold=0.20,
    )

    result = retriever.search("unknown", strategy="lexical", limit=3)

    assert result.decision == "cannot_confirm"
    assert result.candidates == []
    assert list(result) == []
    assert result.rejected_candidates == []


def test_hybrid_search_keeps_rejected_candidates_only_when_debug_enabled() -> None:
    weak_candidate = _candidate(score=0.19, strategy="lexical")
    retriever = HybridRetriever(
        lexical_retriever=StubRetriever([weak_candidate]),
        vector_retriever=StubRetriever([]),
        score_threshold=0.20,
    )

    result = retriever.search("unknown", strategy="lexical", limit=3, debug=True)

    assert result.decision == "cannot_confirm"
    assert result.candidates == []
    assert [candidate.source_id for candidate in result.rejected_candidates] == [
        weak_candidate.source_id
    ]


def test_hybrid_search_reports_retrieval_diagnostics() -> None:
    accepted_candidate = _candidate(score=0.72, strategy="lexical", heading="Accepted")
    rejected_candidate = _candidate(score=0.08, strategy="vector", heading="Rejected")
    retriever = HybridRetriever(
        lexical_retriever=StubRetriever([accepted_candidate]),
        vector_retriever=StubRetriever([rejected_candidate]),
        score_threshold=0.20,
    )

    result = retriever.search("課程網站在哪？", strategy="hybrid", limit=3, debug=True)

    assert result.diagnostics.strategy == "hybrid"
    assert result.diagnostics.requested_limit == 3
    assert result.diagnostics.score_threshold == pytest.approx(0.20)
    assert result.diagnostics.raw_candidate_count == 2
    assert result.diagnostics.merged_candidate_count == 2
    assert result.diagnostics.accepted_count == 1
    assert result.diagnostics.rejected_count == 1
    assert result.diagnostics.top_score == pytest.approx(0.72)
    assert result.diagnostics.selected_source_ids == (accepted_candidate.source_id,)
    assert result.diagnostics.rejected_source_ids == (rejected_candidate.source_id,)
    assert result.diagnostics.strategy_counts == {"lexical": 1, "vector": 1}
    assert result.diagnostics.score_debug_by_source_id[accepted_candidate.source_id]


def test_hybrid_search_respects_strategy_selection() -> None:
    lexical_candidate = _candidate(score=0.75, strategy="lexical")
    vector_candidate = _candidate(score=0.70, strategy="vector", heading="Vector")
    lexical = StubRetriever([lexical_candidate])
    vector = StubRetriever([vector_candidate])
    retriever = HybridRetriever(
        lexical_retriever=lexical,
        vector_retriever=vector,
        score_threshold=0.10,
    )

    lexical_result = retriever.search("課程網站在哪？", strategy="lexical", limit=2)
    vector_result = retriever.search("課程網站在哪？", strategy="vector", limit=2)
    hybrid_result = retriever.search("課程網站在哪？", strategy="hybrid", limit=2)

    assert [candidate.strategy for candidate in lexical_result] == ["lexical"]
    assert [candidate.strategy for candidate in vector_result] == ["vector"]
    assert {candidate.strategy for candidate in hybrid_result} == {"lexical", "vector"}
    assert lexical.calls == [("課程網站在哪？", 2), ("課程網站在哪？", 2)]
    assert vector.calls == [("課程網站在哪？", 2), ("課程網站在哪？", 2)]


def test_hybrid_search_rejects_unknown_strategy() -> None:
    retriever = HybridRetriever(
        lexical_retriever=StubRetriever([]),
        vector_retriever=StubRetriever([]),
    )

    with pytest.raises(ValueError, match="unsupported retrieval strategy"):
        retriever.search("query", strategy=cast(Any, "semantic"))


def _candidate(
    *,
    section_id: UUID | None = None,
    score: float,
    strategy: str,
    heading: str = "Course Site",
    source_type: str = "markdown",
    source_priority: int = 0,
) -> RetrievedCandidate:
    candidate_section_id = section_id or uuid4()
    return RetrievedCandidate(
        section_id=candidate_section_id,
        source_id=f"faq.md#{heading.lower().replace(' ', '-')}",
        filename="faq.md",
        heading=heading,
        body_md=f"## {heading}\n\nBody",
        score=score,
        strategy=strategy,
        source_type=source_type,
        source_priority=source_priority,
    )
