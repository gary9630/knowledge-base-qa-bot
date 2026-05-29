from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.answer.providers import FakeAnswerProvider
from app.evals.service import EvalCaseInput, EvaluationService
from app.retrieval.models import RetrievalResult, RetrievedCandidate


class StubRetriever:
    def __init__(self, result: RetrievalResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []

    def search(self, query: str, *, strategy: str, limit: int) -> RetrievalResult:
        self.calls.append((query, strategy, limit))
        return self.result


def test_evaluation_service_passes_when_decision_and_cited_source_match() -> None:
    candidate = _candidate(source_id="faq.md#course-site")
    service = EvaluationService(
        retriever=StubRetriever(RetrievalResult(decision="can_answer", candidates=[candidate])),
        answer_provider=FakeAnswerProvider(["課程網站在首頁。 [faq.md#course-site]"]),
    )
    case = EvalCaseInput(
        id=uuid4(),
        name="course site",
        query="課程網站在哪？",
        expected_decision="can_answer",
        expected_source_ids=("faq.md#course-site",),
    )

    result = service.evaluate_case(case, strategy="hybrid", limit=3)

    assert result.passed is True
    assert result.actual_decision == "can_answer"
    assert result.score == pytest.approx(1.0)
    assert result.selected_source_ids == ("faq.md#course-site",)
    assert result.cited_source_ids == ("faq.md#course-site",)
    assert result.missing_source_ids == ()
    assert result.metrics == {
        "decision_match": 1.0,
        "top1_hit": 1.0,
        "retrieval_recall": 1.0,
        "citation_recall": 1.0,
        "citation_precision": 1.0,
        "answer_valid": 1.0,
        "citation_error_count": 0.0,
    }


def test_evaluation_service_fails_when_expected_source_is_not_cited() -> None:
    candidate = _candidate(source_id="faq.md#course-site")
    service = EvaluationService(
        retriever=StubRetriever(RetrievalResult(decision="can_answer", candidates=[candidate])),
        answer_provider=FakeAnswerProvider(["我無法從知識庫確認這件事。"]),
    )
    case = EvalCaseInput(
        id=uuid4(),
        name="course site",
        query="課程網站在哪？",
        expected_decision="can_answer",
        expected_source_ids=("faq.md#course-site",),
    )

    result = service.evaluate_case(case, strategy="hybrid", limit=3)

    assert result.passed is False
    assert result.actual_decision == "cannot_confirm"
    assert result.missing_source_ids == ("faq.md#course-site",)
    assert result.metrics["decision_match"] == 0.0
    assert result.metrics["top1_hit"] == 1.0
    assert result.metrics["retrieval_recall"] == 1.0
    assert result.metrics["citation_recall"] == 0.0
    assert result.metrics["citation_precision"] == 0.0
    assert result.metrics["answer_valid"] == 1.0


def test_evaluation_service_passes_cannot_confirm_without_sources() -> None:
    service = EvaluationService(
        retriever=StubRetriever(RetrievalResult(decision="cannot_confirm", candidates=[])),
        answer_provider=FakeAnswerProvider(),
    )
    case = EvalCaseInput(
        id=uuid4(),
        name="unknown",
        query="不存在的資訊？",
        expected_decision="cannot_confirm",
    )

    result = service.evaluate_case(case, strategy="hybrid", limit=3)

    assert result.passed is True
    assert result.actual_decision == "cannot_confirm"
    assert result.score == pytest.approx(1.0)
    assert result.selected_source_ids == ()
    assert result.cited_source_ids == ()


def test_evaluation_service_summarizes_empty_runs_as_zero_score() -> None:
    service = EvaluationService(
        retriever=StubRetriever(RetrievalResult(decision="cannot_confirm", candidates=[])),
        answer_provider=FakeAnswerProvider(),
    )

    summary = service.summarize([])

    assert summary.total == 0
    assert summary.passed == 0
    assert summary.failed == 0
    assert summary.pass_rate == 0.0
    assert summary.average_score == 0.0


def _candidate(*, source_id: str, section_id: UUID | None = None) -> RetrievedCandidate:
    return RetrievedCandidate(
        section_id=section_id or uuid4(),
        source_id=source_id,
        filename=source_id.split("#", 1)[0],
        heading="Course Site",
        body_md="## Course Site\n\n課程網站在首頁。",
        score=0.9,
        strategy="hybrid",
    )
