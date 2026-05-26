from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import (
    get_answer_provider,
    get_embedding_provider,
    get_request_db_session,
    require_admin_access,
)
from app.evals.service import EvalCaseInput, EvalCaseResult, EvaluationService
from app.models.tables import EvalCase, EvalResult, EvalRun
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.models import RetrievalDecision, RetrievalStrategy

router = APIRouter()
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EvalCaseCreateRequest(BaseModel):
    name: NonEmptyStr
    query: NonEmptyStr
    expected_decision: RetrievalDecision
    expected_source_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    active: bool = True


class EvalCaseResponse(BaseModel):
    id: UUID
    name: str
    query: str
    expected_decision: RetrievalDecision
    expected_source_ids: list[str]
    tags: list[str]
    metadata: dict[str, object]
    active: bool
    created_at: str
    updated_at: str


class EvalCasesResponse(BaseModel):
    cases: list[EvalCaseResponse]


class EvalRunRequest(BaseModel):
    case_ids: list[UUID] | None = None
    strategy: RetrievalStrategy = "hybrid"
    limit: int = Field(default=5, ge=1, le=20)


class EvalResultResponse(BaseModel):
    id: UUID | None = None
    case_id: UUID
    name: str
    query: str
    expected_decision: RetrievalDecision
    actual_decision: RetrievalDecision
    passed: bool
    score: float
    answer: str | None
    expected_source_ids: list[str]
    selected_source_ids: list[str]
    cited_source_ids: list[str]
    missing_source_ids: list[str]
    unexpected_source_ids: list[str]
    metrics: dict[str, float]
    error: str | None = None


class EvalRunResponse(BaseModel):
    id: UUID
    status: str
    strategy: RetrievalStrategy
    limit: int
    stats: dict[str, object]
    error: str | None
    created_at: str
    updated_at: str
    results: list[EvalResultResponse]


@router.get(
    "/evals/cases",
    response_model=EvalCasesResponse,
    dependencies=[Depends(require_admin_access)],
)
def list_eval_cases(
    session: Annotated[Session, Depends(get_request_db_session)],
) -> EvalCasesResponse:
    cases = session.scalars(
        select(EvalCase).order_by(EvalCase.created_at.desc(), EvalCase.id.desc())
    ).all()
    return EvalCasesResponse(cases=[eval_case_response(case) for case in cases])


@router.post(
    "/evals/cases",
    response_model=EvalCaseResponse,
    dependencies=[Depends(require_admin_access)],
)
def create_eval_case(
    payload: EvalCaseCreateRequest,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> EvalCaseResponse:
    eval_case = EvalCase(
        name=payload.name,
        query=payload.query,
        expected_decision=payload.expected_decision,
        expected_sources_json=_unique_strings(payload.expected_source_ids),
        tags_json=_unique_strings(payload.tags),
        metadata_json=dict(payload.metadata),
        active=payload.active,
    )
    session.add(eval_case)
    session.commit()
    return eval_case_response(eval_case)


@router.post(
    "/evals/run",
    response_model=EvalRunResponse,
    dependencies=[Depends(require_admin_access)],
)
def run_evals(
    payload: EvalRunRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> EvalRunResponse:
    cases = _cases_for_run(session, payload.case_ids)
    eval_run = EvalRun(
        status="running",
        strategy=payload.strategy,
        limit=payload.limit,
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
                embedding_provider=get_embedding_provider(request),
            ),
            answer_provider=get_answer_provider(request),
        )
        results = [
            service.evaluate_case(
                _eval_case_input(case),
                strategy=payload.strategy,
                limit=payload.limit,
            )
            for case in cases
        ]
    except Exception as error:
        _mark_run_failed(session, run_id, case_count=len(cases), error=error)
        raise HTTPException(status_code=500, detail="Eval run failed.") from error

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
    return eval_run_response(eval_run, persisted_results)


@router.get(
    "/evals/runs/latest",
    response_model=EvalRunResponse,
    dependencies=[Depends(require_admin_access)],
)
def latest_eval_run(
    session: Annotated[Session, Depends(get_request_db_session)],
) -> EvalRunResponse:
    eval_run = session.scalar(
        select(EvalRun)
        .options(selectinload(EvalRun.results).selectinload(EvalResult.case))
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .limit(1)
    )
    if eval_run is None:
        raise HTTPException(status_code=404, detail="Eval run not found.")
    return eval_run_response(eval_run, list(eval_run.results))


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
            missing_text = ", ".join(str(case_id) for case_id in missing_ids)
            raise HTTPException(
                status_code=404,
                detail=f"Eval cases not found or inactive: {missing_text}",
            )
    elif not cases:
        raise HTTPException(status_code=409, detail="No active eval cases found.")
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
        raise HTTPException(status_code=500, detail="Eval run not found.")
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


def eval_case_response(eval_case: EvalCase) -> EvalCaseResponse:
    return EvalCaseResponse(
        id=eval_case.id,
        name=eval_case.name,
        query=eval_case.query,
        expected_decision=eval_case.expected_decision,  # type: ignore[arg-type]
        expected_source_ids=list(eval_case.expected_sources_json),
        tags=list(eval_case.tags_json),
        metadata=dict(eval_case.metadata_json),
        active=eval_case.active,
        created_at=eval_case.created_at.isoformat(),
        updated_at=eval_case.updated_at.isoformat(),
    )


def eval_run_response(eval_run: EvalRun, results: list[EvalResult]) -> EvalRunResponse:
    sorted_results = sorted(results, key=lambda result: (result.created_at, result.id))
    return EvalRunResponse(
        id=eval_run.id,
        status=eval_run.status,
        strategy=eval_run.strategy,  # type: ignore[arg-type]
        limit=eval_run.limit,
        stats=dict(eval_run.stats_json),
        error=eval_run.error,
        created_at=eval_run.created_at.isoformat(),
        updated_at=eval_run.updated_at.isoformat(),
        results=[eval_result_response(result) for result in sorted_results],
    )


def eval_result_response(result: EvalResult) -> EvalResultResponse:
    return EvalResultResponse(
        id=result.id,
        case_id=result.case_id,
        name=result.case.name if result.case is not None else "",
        query=result.query,
        expected_decision=result.expected_decision,  # type: ignore[arg-type]
        actual_decision=result.actual_decision,  # type: ignore[arg-type]
        passed=result.passed,
        score=result.score,
        answer=result.answer,
        expected_source_ids=list(result.expected_sources_json),
        selected_source_ids=list(result.selected_sources_json),
        cited_source_ids=list(result.cited_sources_json),
        missing_source_ids=list(result.missing_sources_json),
        unexpected_source_ids=list(result.unexpected_sources_json),
        metrics=dict(result.metrics_json),
        error=result.error,
    )


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        unique_values.append(stripped)
    return unique_values


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
