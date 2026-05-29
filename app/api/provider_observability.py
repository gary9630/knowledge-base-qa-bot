from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_request_db_session, require_admin_access
from app.models.tables import RetrievalEvent
from app.observability.metrics import InMemoryMetrics

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_access)])


class ProviderUsageResponse(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


class ProviderCallResponse(BaseModel):
    provider: str
    operation: str
    model: str
    status: str
    client_request_id: str | None = None
    provider_request_id: str | None = None
    usage: ProviderUsageResponse | None = None
    usage_complete: bool = False
    latency_ms: int = 0
    error_type: str | None = None


class ProviderUsageByKeyResponse(BaseModel):
    key: str
    calls: int
    usage: ProviderUsageResponse


class ProviderSummaryResponse(BaseModel):
    total_calls: int
    error_calls: int
    error_rate: float
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    reasoning_tokens: int


class ProviderTraceResponse(BaseModel):
    retrieval_event_id: UUID
    conversation_id: UUID | None
    message_id: UUID | None
    query: str
    strategy: str
    decision: str
    latency_ms: int | None
    created_at: str
    provider_calls: list[ProviderCallResponse]


class ProviderObservabilityResponse(BaseModel):
    summary: ProviderSummaryResponse
    usage_by_key: list[ProviderUsageByKeyResponse]
    latest_calls: list[ProviderCallResponse]
    traces: list[ProviderTraceResponse]


@router.get("/provider-observability", response_model=ProviderObservabilityResponse)
def get_provider_observability(
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ProviderObservabilityResponse:
    metrics = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics, InMemoryMetrics):
        metrics = InMemoryMetrics()
        request.app.state.metrics = metrics

    events = session.scalars(
        select(RetrievalEvent)
        .order_by(RetrievalEvent.created_at.desc(), RetrievalEvent.id.desc())
        .limit(limit * 5)
    ).all()
    traces: list[ProviderTraceResponse] = []
    for event in events:
        trace = provider_trace_response(event)
        if trace is not None:
            traces.append(trace)
        if len(traces) >= limit:
            break

    return provider_observability_response(
        metrics_snapshot=metrics.snapshot(),
        traces=traces,
    )


def provider_observability_response(
    *,
    metrics_snapshot: dict[str, Any],
    traces: list[ProviderTraceResponse],
) -> ProviderObservabilityResponse:
    calls_by_key = _dict_value(metrics_snapshot.get("provider_calls_by_key"))
    usage_by_key_payload = _dict_value(metrics_snapshot.get("provider_usage_by_key"))
    usage_by_key = [
        ProviderUsageByKeyResponse(
            key=key,
            calls=_int_value(calls_by_key.get(key)),
            usage=_usage_response(usage_by_key_payload.get(key)),
        )
        for key in sorted(set(calls_by_key) | set(usage_by_key_payload))
    ]
    usage_totals = _usage_totals([item.usage for item in usage_by_key])
    total_calls = _int_value(metrics_snapshot.get("provider_calls_total"))
    error_calls = _int_value(metrics_snapshot.get("provider_errors_total"))
    latest_calls = [
        call
        for call in (
            _provider_call_response(item)
            for item in _list_value(metrics_snapshot.get("latest_provider_calls"))
        )
        if call is not None
    ]
    return ProviderObservabilityResponse(
        summary=ProviderSummaryResponse(
            total_calls=total_calls,
            error_calls=error_calls,
            error_rate=(error_calls / total_calls if total_calls else 0.0),
            total_tokens=usage_totals.total_tokens,
            prompt_tokens=usage_totals.prompt_tokens,
            completion_tokens=usage_totals.completion_tokens,
            cached_tokens=usage_totals.cached_tokens,
            reasoning_tokens=usage_totals.reasoning_tokens,
        ),
        usage_by_key=usage_by_key,
        latest_calls=latest_calls,
        traces=traces,
    )


def provider_trace_response(event: RetrievalEvent) -> ProviderTraceResponse | None:
    provider_calls_payload = _list_value(event.scores_json.get("provider_calls"))
    provider_calls = [
        call
        for call in (
            _provider_call_response(item) for item in provider_calls_payload
        )
        if call is not None
    ]
    if not provider_calls:
        return None
    return ProviderTraceResponse(
        retrieval_event_id=event.id,
        conversation_id=event.conversation_id,
        message_id=event.message_id,
        query=event.query,
        strategy=event.strategy,
        decision=event.decision,
        latency_ms=event.latency_ms,
        created_at=event.created_at.isoformat() if event.created_at else "",
        provider_calls=provider_calls,
    )


def _provider_call_response(payload: object) -> ProviderCallResponse | None:
    if not isinstance(payload, dict):
        return None
    provider = _str_value(payload.get("provider"))
    operation = _str_value(payload.get("operation"))
    model = _str_value(payload.get("model"))
    status = _str_value(payload.get("status"))
    if not provider or not operation or not model or not status:
        return None
    return ProviderCallResponse(
        provider=provider,
        operation=operation,
        model=model,
        status=status,
        client_request_id=_str_value(payload.get("client_request_id")) or None,
        provider_request_id=_str_value(payload.get("provider_request_id")) or None,
        usage=_usage_response(payload.get("usage")) if payload.get("usage") else None,
        usage_complete=bool(payload.get("usage_complete")),
        latency_ms=_int_value(payload.get("latency_ms")),
        error_type=_str_value(payload.get("error_type")) or None,
    )


def _usage_response(payload: object) -> ProviderUsageResponse:
    values = _dict_value(payload)
    return ProviderUsageResponse(
        prompt_tokens=_int_value(values.get("prompt_tokens")),
        completion_tokens=_int_value(values.get("completion_tokens")),
        total_tokens=_int_value(values.get("total_tokens")),
        cached_tokens=_int_value(values.get("cached_tokens")),
        reasoning_tokens=_int_value(values.get("reasoning_tokens")),
    )


def _usage_totals(usages: list[ProviderUsageResponse]) -> ProviderUsageResponse:
    return ProviderUsageResponse(
        prompt_tokens=sum(usage.prompt_tokens for usage in usages),
        completion_tokens=sum(usage.completion_tokens for usage in usages),
        total_tokens=sum(usage.total_tokens for usage in usages),
        cached_tokens=sum(usage.cached_tokens for usage in usages),
        reasoning_tokens=sum(usage.reasoning_tokens for usage in usages),
    )


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _str_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0
