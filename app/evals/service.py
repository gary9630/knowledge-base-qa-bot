from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.answer.citations import CANNOT_CONFIRM_ANSWER
from app.answer.context_assembly import AssembledContext
from app.answer.providers import AnswerProvider
from app.answer.service import AnswerResult, AnswerService
from app.retrieval.models import (
    RetrievalDecision,
    RetrievalResult,
    RetrievalStrategy,
    RetrievedCandidate,
)


@dataclass(frozen=True)
class EvalCaseInput:
    id: UUID
    name: str
    query: str
    expected_decision: RetrievalDecision
    expected_source_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: UUID
    name: str
    query: str
    expected_decision: RetrievalDecision
    actual_decision: RetrievalDecision
    passed: bool
    score: float
    answer: str
    expected_source_ids: tuple[str, ...]
    selected_source_ids: tuple[str, ...]
    cited_source_ids: tuple[str, ...]
    missing_source_ids: tuple[str, ...]
    unexpected_source_ids: tuple[str, ...]
    metrics: dict[str, float]


@dataclass(frozen=True)
class EvalRunSummary:
    total: int
    passed: int
    failed: int
    pass_rate: float
    average_score: float


class EvaluationRetriever(Protocol):
    def search(
        self,
        query: str,
        *,
        strategy: RetrievalStrategy,
        limit: int,
    ) -> RetrievalResult: ...


class EvaluationContextAssembler(Protocol):
    def assemble(self, candidates: Sequence[RetrievedCandidate]) -> AssembledContext: ...


class EvaluationService:
    def __init__(
        self,
        *,
        retriever: EvaluationRetriever,
        answer_provider: AnswerProvider,
        context_assembler: EvaluationContextAssembler,
    ) -> None:
        self.retriever = retriever
        self.answer_provider = answer_provider
        self.context_assembler = context_assembler

    def evaluate_case(
        self,
        case: EvalCaseInput,
        *,
        strategy: RetrievalStrategy,
        limit: int,
    ) -> EvalCaseResult:
        retrieval_result = self.retriever.search(case.query, strategy=strategy, limit=limit)
        assembled = self.context_assembler.assemble(retrieval_result.candidates)
        answer_result = AnswerService(self.answer_provider).answer(
            case.query,
            assembled.sources,
        )
        actual_decision = _answer_decision(retrieval_result.decision, answer_result)
        selected_source_ids = tuple(
            candidate.source_id for candidate in retrieval_result.candidates
        )
        cited_source_ids = tuple(source.source_id for source in answer_result.sources)
        expected_source_ids = _unique(case.expected_source_ids)
        missing_source_ids = tuple(
            source_id for source_id in expected_source_ids if source_id not in cited_source_ids
        )
        unexpected_source_ids = tuple(
            source_id
            for source_id in cited_source_ids
            if expected_source_ids and source_id not in expected_source_ids
        )
        metrics = _metrics(
            expected_decision=case.expected_decision,
            actual_decision=actual_decision,
            expected_source_ids=expected_source_ids,
            selected_source_ids=selected_source_ids,
            cited_source_ids=cited_source_ids,
            answer_valid=answer_result.valid,
            citation_error_count=len(answer_result.citation_errors),
        )
        passed = _passed(
            expected_decision=case.expected_decision,
            actual_decision=actual_decision,
            expected_source_ids=expected_source_ids,
            cited_source_ids=cited_source_ids,
            metrics=metrics,
        )

        return EvalCaseResult(
            case_id=case.id,
            name=case.name,
            query=case.query,
            expected_decision=case.expected_decision,
            actual_decision=actual_decision,
            passed=passed,
            score=_score(metrics),
            answer=answer_result.answer,
            expected_source_ids=expected_source_ids,
            selected_source_ids=selected_source_ids,
            cited_source_ids=cited_source_ids,
            missing_source_ids=missing_source_ids,
            unexpected_source_ids=unexpected_source_ids,
            metrics=metrics,
        )

    def summarize(self, results: list[EvalCaseResult]) -> EvalRunSummary:
        total = len(results)
        passed = sum(1 for result in results if result.passed)
        failed = total - passed
        average_score = sum(result.score for result in results) / total if total > 0 else 0.0
        return EvalRunSummary(
            total=total,
            passed=passed,
            failed=failed,
            pass_rate=passed / total if total > 0 else 0.0,
            average_score=average_score,
        )


def _answer_decision(
    retrieval_decision: RetrievalDecision,
    answer_result: AnswerResult,
) -> RetrievalDecision:
    if (
        retrieval_decision != "can_answer"
        or not answer_result.valid
        or not answer_result.sources
        or answer_result.answer == CANNOT_CONFIRM_ANSWER
    ):
        return "cannot_confirm"
    return "can_answer"


def _metrics(
    *,
    expected_decision: RetrievalDecision,
    actual_decision: RetrievalDecision,
    expected_source_ids: tuple[str, ...],
    selected_source_ids: tuple[str, ...],
    cited_source_ids: tuple[str, ...],
    answer_valid: bool,
    citation_error_count: int,
) -> dict[str, float]:
    return {
        "decision_match": 1.0 if actual_decision == expected_decision else 0.0,
        "top1_hit": _top1_hit(expected_source_ids, selected_source_ids),
        "retrieval_recall": _recall(expected_source_ids, selected_source_ids),
        "citation_recall": _citation_recall(expected_source_ids, cited_source_ids),
        "citation_precision": _citation_precision(expected_source_ids, cited_source_ids),
        "answer_valid": 1.0 if answer_valid else 0.0,
        "citation_error_count": float(citation_error_count),
    }


def _passed(
    *,
    expected_decision: RetrievalDecision,
    actual_decision: RetrievalDecision,
    expected_source_ids: tuple[str, ...],
    cited_source_ids: tuple[str, ...],
    metrics: dict[str, float],
) -> bool:
    if expected_decision != actual_decision:
        return False
    if expected_decision == "cannot_confirm":
        return not cited_source_ids
    if not expected_source_ids:
        return True
    return (
        metrics["retrieval_recall"] == 1.0
        and metrics["citation_recall"] == 1.0
    )


def _score(metrics: dict[str, float]) -> float:
    if not metrics:
        return 0.0
    score_values = [
        value for key, value in metrics.items() if not key.endswith("_count")
    ]
    return sum(score_values) / len(score_values) if score_values else 0.0


def _recall(expected_source_ids: tuple[str, ...], actual_source_ids: tuple[str, ...]) -> float:
    if not expected_source_ids:
        return 1.0
    matched = sum(1 for source_id in expected_source_ids if source_id in actual_source_ids)
    return matched / len(expected_source_ids)


def _citation_recall(
    expected_source_ids: tuple[str, ...],
    cited_source_ids: tuple[str, ...],
) -> float:
    if expected_source_ids:
        return _recall(expected_source_ids, cited_source_ids)
    return 1.0 if not cited_source_ids else 0.0


def _top1_hit(
    expected_source_ids: tuple[str, ...],
    selected_source_ids: tuple[str, ...],
) -> float:
    if not expected_source_ids:
        return 1.0
    if not selected_source_ids:
        return 0.0
    return 1.0 if selected_source_ids[0] in expected_source_ids else 0.0


def _citation_precision(
    expected_source_ids: tuple[str, ...],
    cited_source_ids: tuple[str, ...],
) -> float:
    if not cited_source_ids:
        return 1.0 if not expected_source_ids else 0.0
    if not expected_source_ids:
        return 0.0
    matched = sum(1 for source_id in cited_source_ids if source_id in expected_source_ids)
    return matched / len(cited_source_ids)


def _unique(source_ids: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique_source_ids: list[str] = []
    for source_id in source_ids:
        if source_id in seen:
            continue
        seen.add(source_id)
        unique_source_ids.append(source_id)
    return tuple(unique_source_ids)
