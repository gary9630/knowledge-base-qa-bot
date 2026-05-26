from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.answer.providers import AnswerProvider
from app.evals.service import EvalCaseInput, EvalCaseResult, EvaluationService
from app.models.tables import EvalCase, EvalResult, EvalRun
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.models import RetrievalStrategy


class NoActiveEvalCasesError(ValueError):
    pass


class EvalCasesNotFoundError(ValueError):
    def __init__(self, missing_ids: list[UUID]) -> None:
        self.missing_ids = missing_ids
        missing_text = ", ".join(str(case_id) for case_id in missing_ids)
        super().__init__(f"Eval cases not found or inactive: {missing_text}")


class EvalExecutionFailedError(RuntimeError):
    def __init__(self, run_id: UUID, message: str) -> None:
        self.run_id = run_id
        super().__init__(message)


@dataclass(frozen=True)
class EvalRunOptions:
    trigger: str = "manual"
    strategy: RetrievalStrategy = "hybrid"
    limit: int = 5
    case_ids: tuple[UUID, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EvalRunExecution:
    run_id: UUID
    status: str
    stats: dict[str, object]


def run_eval_suite(
    *,
    session: Session,
    embedding_provider: EmbeddingProvider,
    answer_provider: AnswerProvider,
    options: EvalRunOptions,
) -> tuple[EvalRun, list[EvalResult]]:
    cases = _cases_for_run(session, list(options.case_ids) or None)
    eval_run = EvalRun(
        status="running",
        strategy=options.strategy,
        limit=options.limit,
        trigger=options.trigger,
        stats_json={
            "total": len(cases),
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "average_score": 0.0,
        },
    )
    session.add(eval_run)
    session.commit()
    run_id = eval_run.id

    try:
        service = EvaluationService(
            retriever=HybridRetriever(
                session=session,
                embedding_provider=embedding_provider,
            ),
            answer_provider=answer_provider,
        )
        results = [
            service.evaluate_case(
                _eval_case_input(case),
                strategy=options.strategy,
                limit=options.limit,
            )
            for case in cases
        ]
    except Exception as error:
        _mark_run_failed(session, run_id, case_count=len(cases), error=error)
        raise EvalExecutionFailedError(run_id, "Eval run failed.") from error

    summary = service.summarize(results)
    eval_run = _require_eval_run(session, run_id)
    eval_run.status = "succeeded"
    eval_run.error = None
    eval_run.stats_json = {
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "pass_rate": summary.pass_rate,
        "average_score": summary.average_score,
    }

    persisted_results = []
    for result in results:
        persisted_result = _eval_result_model(eval_run.id, result)
        session.add(persisted_result)
        persisted_results.append(persisted_result)

    session.commit()
    return eval_run, persisted_results


def execution_from_run(eval_run: EvalRun) -> EvalRunExecution:
    return EvalRunExecution(
        run_id=eval_run.id,
        status=eval_run.status,
        stats=dict(eval_run.stats_json),
    )


def _cases_for_run(session: Session, case_ids: list[UUID] | None) -> list[EvalCase]:
    requested_ids = _unique_uuids(case_ids or [])
    statement = select(EvalCase).where(EvalCase.active.is_(True))
    if requested_ids:
        statement = statement.where(EvalCase.id.in_(requested_ids))
    cases = list(
        session.scalars(statement.order_by(EvalCase.created_at.asc(), EvalCase.id.asc())).all()
    )
    if requested_ids:
        found_ids = {case.id for case in cases}
        missing_ids = [case_id for case_id in requested_ids if case_id not in found_ids]
        if missing_ids:
            raise EvalCasesNotFoundError(missing_ids)
    elif not cases:
        raise NoActiveEvalCasesError("No active eval cases found.")
    return cases


def _mark_run_failed(
    session: Session,
    run_id: UUID,
    *,
    case_count: int,
    error: Exception,
) -> None:
    session.rollback()
    eval_run = _require_eval_run(session, run_id)
    eval_run.status = "failed"
    eval_run.error = _error_message(error)
    eval_run.stats_json = {
        "total": case_count,
        "passed": 0,
        "failed": case_count,
        "pass_rate": 0.0,
        "average_score": 0.0,
    }
    session.commit()


def _require_eval_run(session: Session, run_id: UUID) -> EvalRun:
    eval_run = session.get(EvalRun, run_id)
    if eval_run is None:
        raise EvalExecutionFailedError(run_id, "Eval run not found.")
    return eval_run


def _eval_case_input(eval_case: EvalCase) -> EvalCaseInput:
    return EvalCaseInput(
        id=eval_case.id,
        name=eval_case.name,
        query=eval_case.query,
        expected_decision=eval_case.expected_decision,  # type: ignore[arg-type]
        expected_source_ids=tuple(eval_case.expected_sources_json),
        tags=tuple(eval_case.tags_json),
        metadata=dict(eval_case.metadata_json),
    )


def _eval_result_model(run_id: UUID, result: EvalCaseResult) -> EvalResult:
    return EvalResult(
        run_id=run_id,
        case_id=result.case_id,
        query=result.query,
        expected_decision=result.expected_decision,
        actual_decision=result.actual_decision,
        passed=result.passed,
        score=result.score,
        answer=result.answer,
        expected_sources_json=list(result.expected_source_ids),
        selected_sources_json=list(result.selected_source_ids),
        cited_sources_json=list(result.cited_source_ids),
        missing_sources_json=list(result.missing_source_ids),
        unexpected_sources_json=list(result.unexpected_source_ids),
        metrics_json=dict(result.metrics),
    )


def _unique_uuids(values: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    unique_values: list[UUID] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _error_message(error: Exception) -> str:
    message = str(error).strip()
    return message or error.__class__.__name__
