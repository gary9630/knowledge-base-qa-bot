from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.retrieval.hybrid import RRF_K, HybridRetriever, fuse_results
from app.retrieval.models import RetrievedCandidate


class StubRetriever:
    def __init__(self, candidates: list[RetrievedCandidate]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[RetrievedCandidate]:
        self.calls.append((query, limit))
        return self.candidates[:limit]


def test_fuse_results_section_in_both_strategies_outranks_single_strategy() -> None:
    shared_id = uuid4()
    lexical = [
        _candidate(section_id=shared_id, source_id="doc.md#both", score=0.4),
        _candidate(source_id="doc.md#lex-only", score=0.9),
    ]
    vector = [_candidate(section_id=shared_id, source_id="doc.md#both", score=0.3,
                         strategy="vector")]

    fused = fuse_results({"lexical": lexical, "vector": vector})

    assert fused[0].source_id == "doc.md#both"
    assert fused[0].strategy == "hybrid"
    # rank 1 in both strategies -> normalized RRF == 1.0
    assert fused[0].score == 1.0


def test_fuse_results_single_strategy_rank_one_scores_half() -> None:
    fused = fuse_results({"lexical": [_candidate(source_id="doc.md#only", score=0.8)]})

    assert len(fused) == 1
    assert fused[0].score == 0.5
    assert fused[0].strategy == "lexical"
    assert fused[0].debug_scores["lexical_rank"] == 1.0


def test_fuse_results_applies_source_priority_boost_after_normalization() -> None:
    plain = fuse_results({"lexical": [_candidate(source_id="doc.md#plain", score=0.8)]})
    boosted = fuse_results(
        {"lexical": [_candidate(source_id="doc.md#policy", score=0.8, source_priority=5)]}
    )

    assert boosted[0].score == min(1.0, plain[0].score + 0.05)
    assert boosted[0].debug_scores["source_priority_boost"] == 0.05


def test_fuse_results_prefers_lexical_body_on_rank_tie() -> None:
    shared_id = uuid4()
    lexical_candidate = RetrievedCandidate(
        section_id=shared_id,
        source_id="doc.md#both",
        filename="doc.md",
        heading="Heading",
        body_md="FULL SECTION BODY",
        score=0.4,
        strategy="lexical",
    )
    vector_candidate = RetrievedCandidate(
        section_id=shared_id,
        source_id="doc.md#both",
        filename="doc.md",
        heading="Heading",
        body_md="chunk text only",
        score=0.9,
        strategy="vector",
    )

    fused = fuse_results({"lexical": [lexical_candidate], "vector": [vector_candidate]})

    assert fused[0].body_md == "FULL SECTION BODY"


def test_rrf_constant_is_sixty() -> None:
    assert RRF_K == 60


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
    assert result.diagnostics.merged_candidate_count == 1  # only lexical passed pre-fusion floor
    assert result.diagnostics.accepted_count == 1
    assert result.diagnostics.rejected_count == 1
    assert result.diagnostics.top_score == pytest.approx(0.5)  # single-strategy rank-1 RRF = 0.5
    assert result.diagnostics.selected_source_ids == (accepted_candidate.source_id,)
    assert result.diagnostics.rejected_source_ids == (rejected_candidate.source_id,)
    assert result.diagnostics.strategy_counts == {"lexical": 1, "vector": 1}
    assert result.diagnostics.score_debug_by_source_id[accepted_candidate.source_id]


def test_hybrid_search_boosts_exact_query_match_above_tied_generic_match() -> None:
    generic_website_match = _candidate(
        score=0.30,
        strategy="lexical",
        filename="network.md",
        heading="L4 vs L7",
        body_md="## L4 vs L7\n\nREST、HTTP API、網站",
    )
    faq_match = _candidate(
        score=0.30,
        strategy="lexical",
        filename="常見問題FAQ.md",
        heading="常見問題FAQ",
        body_md="問題：課程網站在哪？\n答覆：課程網站是 https://buildmoat.org/",
    )
    retriever = HybridRetriever(
        lexical_retriever=StubRetriever([generic_website_match, faq_match]),
        vector_retriever=StubRetriever([]),
        score_threshold=0.10,
    )

    result = retriever.search("課程網站在哪裡？", strategy="hybrid", limit=2)

    assert result.candidates[0].source_id == faq_match.source_id
    assert result.candidates[0].score > generic_website_match.score
    assert result.candidates[0].debug_scores["query_relevance_boost"] > 0


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
    source_id: str | None = None,
    score: float = 0.5,
    strategy: str = "lexical",
    filename: str = "faq.md",
    heading: str = "Course Site",
    body_md: str | None = None,
    source_type: str = "markdown",
    source_priority: int = 0,
) -> RetrievedCandidate:
    candidate_section_id = section_id or uuid4()
    return RetrievedCandidate(
        section_id=candidate_section_id,
        source_id=source_id or f"faq.md#{heading.lower().replace(' ', '-')}",
        filename=filename,
        heading=heading,
        body_md=body_md or f"## {heading}\n\nBody",
        score=score,
        strategy=strategy,
        source_type=source_type,
        source_priority=source_priority,
    )
