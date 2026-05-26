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
from app.evals.cases import (
    EvalSeedSummary,
    load_default_seed_cases,
    parse_seed_cases,
    promote_feedback_to_eval_case,
    seed_eval_cases,
)
from app.evals.reporting import build_eval_report
from app.evals.runner import (
    EvalCasesNotFoundError,
    EvalExecutionFailedError,
    EvalRunOptions,
    NoActiveEvalCasesError,
    run_eval_suite,
)
from app.models.tables import EvalCase, EvalResult, EvalRun
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


class EvalSeedCaseRequest(BaseModel):
    seed_key: NonEmptyStr
    name: NonEmptyStr
    query: NonEmptyStr
    expected_decision: RetrievalDecision
    expected_source_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    active: bool = True


class EvalSeedRequest(BaseModel):
    cases: list[EvalSeedCaseRequest] = Field(default_factory=list)


class EvalFeedbackPromotionRequest(BaseModel):
    feedback_id: UUID
    expected_decision: RetrievalDecision | None = None
    expected_source_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    active: bool = True


class EvalCaseResponse(BaseModel):
    id: UUID
    name: str
    query: str
    expected_decision: RetrievalDecision
    source_kind: str
    seed_key: str | None
    promoted_feedback_id: UUID | None
    expected_source_ids: list[str]
    tags: list[str]
    metadata: dict[str, object]
    active: bool
    created_at: str
    updated_at: str


class EvalCasesResponse(BaseModel):
    cases: list[EvalCaseResponse]


class EvalSeedSummaryResponse(BaseModel):
    created: int
    updated: int
    total: int


class EvalSeedResponse(BaseModel):
    summary: EvalSeedSummaryResponse
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
    trigger: str
    stats: dict[str, object]
    error: str | None
    created_at: str
    updated_at: str
    results: list[EvalResultResponse]


class EvalReportResponse(BaseModel):
    totals: dict[str, object]
    latest_run: dict[str, object] | None
    recent_runs: list[dict[str, object]]
    latest_failures: list[dict[str, object]]
    worst_cases: list[dict[str, object]]


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
    "/evals/seed",
    response_model=EvalSeedResponse,
    dependencies=[Depends(require_admin_access)],
)
def seed_eval_case_set(
    payload: EvalSeedRequest,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> EvalSeedResponse:
    seed_cases = (
        parse_seed_cases([seed_case.model_dump() for seed_case in payload.cases])
        if payload.cases
        else load_default_seed_cases()
    )
    summary, eval_cases = seed_eval_cases(session, seed_cases)
    session.commit()
    return EvalSeedResponse(
        summary=eval_seed_summary_response(summary),
        cases=[eval_case_response(eval_case) for eval_case in eval_cases],
    )


@router.post(
    "/evals/cases/promote-feedback",
    response_model=EvalCaseResponse,
    dependencies=[Depends(require_admin_access)],
)
def promote_feedback_case(
    payload: EvalFeedbackPromotionRequest,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> EvalCaseResponse:
    try:
        eval_case = promote_feedback_to_eval_case(
            session,
            feedback_id=payload.feedback_id,
            expected_decision=payload.expected_decision,
            expected_source_ids=payload.expected_source_ids,
            tags=payload.tags,
            active=payload.active,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

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
    try:
        eval_run, persisted_results = run_eval_suite(
            session=session,
            embedding_provider=get_embedding_provider(request),
            answer_provider=get_answer_provider(request),
            options=EvalRunOptions(
                trigger="api",
                strategy=payload.strategy,
                limit=payload.limit,
                case_ids=tuple(payload.case_ids or []),
            ),
        )
    except NoActiveEvalCasesError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except EvalCasesNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except EvalExecutionFailedError as error:
        raise HTTPException(status_code=500, detail="Eval run failed.") from error

    return eval_run_response(eval_run, persisted_results)


@router.get(
    "/evals/report",
    response_model=EvalReportResponse,
    dependencies=[Depends(require_admin_access)],
)
def eval_report(
    session: Annotated[Session, Depends(get_request_db_session)],
) -> EvalReportResponse:
    return EvalReportResponse(**build_eval_report(session))


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


def eval_case_response(eval_case: EvalCase) -> EvalCaseResponse:
    return EvalCaseResponse(
        id=eval_case.id,
        name=eval_case.name,
        query=eval_case.query,
        expected_decision=eval_case.expected_decision,  # type: ignore[arg-type]
        source_kind=eval_case.source_kind,
        seed_key=eval_case.seed_key,
        promoted_feedback_id=eval_case.promoted_feedback_id,
        expected_source_ids=list(eval_case.expected_sources_json),
        tags=list(eval_case.tags_json),
        metadata=dict(eval_case.metadata_json),
        active=eval_case.active,
        created_at=eval_case.created_at.isoformat(),
        updated_at=eval_case.updated_at.isoformat(),
    )


def eval_seed_summary_response(summary: EvalSeedSummary) -> EvalSeedSummaryResponse:
    return EvalSeedSummaryResponse(
        created=summary.created,
        updated=summary.updated,
        total=summary.total,
    )


def eval_run_response(eval_run: EvalRun, results: list[EvalResult]) -> EvalRunResponse:
    sorted_results = sorted(results, key=lambda result: (result.created_at, result.id))
    return EvalRunResponse(
        id=eval_run.id,
        status=eval_run.status,
        strategy=eval_run.strategy,  # type: ignore[arg-type]
        limit=eval_run.limit,
        trigger=eval_run.trigger,
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
