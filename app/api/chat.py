from __future__ import annotations

import json
from collections.abc import Iterator
from time import perf_counter
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.answer.citations import CANNOT_CONFIRM_ANSWER
from app.answer.providers import AnswerProvider
from app.answer.service import AnswerResult, AnswerService
from app.api.dependencies import (
    get_answer_provider,
    get_app_settings,
    get_embedding_provider,
    get_request_db_session,
    get_source_principal,
)
from app.api.indexing import index_is_ready
from app.api.search import (
    API_RETRIEVAL_SCORE_THRESHOLD,
    CandidateResponse,
    RetrievalDiagnosticsResponse,
    candidate_response,
    retrieval_diagnostics_response,
)
from app.core.config import Settings
from app.models.tables import Conversation, Message, RetrievalEvent
from app.observability.metrics import InMemoryMetrics
from app.observability.middleware import mark_stream_error
from app.provider_budget import provider_budget_status
from app.provider_telemetry import ProviderCallRecord
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.models import (
    RetrievalDecision,
    RetrievalDiagnostics,
    RetrievalResult,
    RetrievalStrategy,
    RetrievedCandidate,
)
from app.source_access import SourcePrincipal, visibility_labels_for_principal

router = APIRouter()

NOT_INDEXED_ANSWER = "知識庫尚未建立索引，請先建立索引。"
PROVIDER_BUDGET_EXCEEDED_DETAIL = "Provider budget exceeded."


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    conversation_id: UUID | None = None
    strategy: RetrievalStrategy = "hybrid"
    limit: int = Field(default=10, ge=1, le=20)


class AnswerQualityResponse(BaseModel):
    answer_valid: bool
    citation_errors: list[str] = Field(default_factory=list)
    selected_source_ids: list[str] = Field(default_factory=list)
    cited_source_ids: list[str] = Field(default_factory=list)
    cannot_confirm_reason: str | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    retrieval_event_id: UUID
    answer: str
    decision: RetrievalDecision
    sources: list[CandidateResponse]
    selected_sources: list[CandidateResponse]
    retrieval_diagnostics: RetrievalDiagnosticsResponse
    answer_quality: AnswerQualityResponse


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
    principal: Annotated[SourcePrincipal, Depends(get_source_principal)],
) -> ChatResponse:
    return _build_chat_response(
        payload=payload,
        request=request,
        session=session,
        principal=principal,
    )


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
    principal: Annotated[SourcePrincipal, Depends(get_source_principal)],
) -> EventSourceResponse:
    _validate_stream_request(payload=payload, session=session)
    return EventSourceResponse(
        _chat_stream_response_events(
            payload=payload,
            request=request,
            session=session,
            principal=principal,
        )
    )


def _build_chat_response(
    *,
    payload: ChatRequest,
    request: Request,
    session: Session,
    principal: SourcePrincipal,
) -> ChatResponse:
    started_at = perf_counter()
    conversation = _conversation_for_request(payload, session)
    user_message = Message(
        conversation=conversation,
        role="user",
        content=payload.query,
    )
    session.add(user_message)
    session.flush()

    if not index_is_ready(session):
        retrieval_diagnostics = _empty_retrieval_diagnostics(payload)
        answer_quality = _answer_quality_response(
            selected_candidates=[],
            answer_result=None,
            cannot_confirm_reason="not_indexed",
        )
        return _persist_chat_response(
            session=session,
            conversation=conversation,
            user_message=user_message,
            query=payload.query,
            strategy=payload.strategy,
            answer=NOT_INDEXED_ANSWER,
            decision="cannot_confirm",
            selected_candidates=[],
            cited_candidates=[],
            retrieval_diagnostics=retrieval_diagnostics,
            answer_quality=answer_quality,
            latency_ms=_elapsed_ms(started_at),
            provider_calls=[],
        )

    retriever = HybridRetriever(
        session=session,
        embedding_provider=get_embedding_provider(request),
        visibility_labels=visibility_labels_for_principal(principal),
        score_threshold=API_RETRIEVAL_SCORE_THRESHOLD,
    )
    retrieval_result = retriever.search(
        payload.query,
        strategy=payload.strategy,
        limit=payload.limit,
    )
    _raise_if_provider_budget_blocked(request)
    answer_result = _answer_provider_error_response(
        provider=get_answer_provider(request),
        payload=payload,
        request=request,
        candidates=retrieval_result.candidates,
    )
    cited_source_ids = {source.source_id for source in answer_result.sources}
    cited_candidates = [
        candidate
        for candidate in retrieval_result.candidates
        if candidate.source_id in cited_source_ids
    ]
    answer_quality = _answer_quality_response(
        selected_candidates=retrieval_result.candidates,
        answer_result=answer_result,
    )

    return _persist_chat_response(
        session=session,
        conversation=conversation,
        user_message=user_message,
        query=payload.query,
        strategy=payload.strategy,
        answer=answer_result.answer,
        decision=_chat_decision(retrieval_result.decision, answer_result),
        selected_candidates=retrieval_result.candidates,
        cited_candidates=cited_candidates,
        retrieval_diagnostics=retrieval_result.diagnostics,
        answer_quality=answer_quality,
        latency_ms=_elapsed_ms(started_at),
        provider_calls=answer_result.provider_calls,
    )


def _answer_provider_error_response(
    *,
    provider: AnswerProvider,
    payload: ChatRequest,
    candidates: list[RetrievedCandidate],
    request: Request | None = None,
) -> AnswerResult:
    answer_service = AnswerService(
        provider,
        client_request_id=_request_id_from_request(request),
    )
    try:
        answer_result = answer_service.answer(payload.query, candidates)
    except Exception as error:
        _record_provider_call_records(request, answer_service.provider_call_records())
        raise HTTPException(status_code=502, detail="Answer provider failed.") from error
    _record_provider_call_records(request, answer_service.provider_call_records())
    return answer_result


def _chat_decision(
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


def _empty_retrieval_diagnostics(payload: ChatRequest) -> RetrievalDiagnostics:
    return RetrievalDiagnostics(
        strategy=payload.strategy,
        requested_limit=payload.limit,
        score_threshold=API_RETRIEVAL_SCORE_THRESHOLD,
    )


def _answer_quality_response(
    *,
    selected_candidates: list[RetrievedCandidate],
    answer_result: AnswerResult | None,
    cannot_confirm_reason: str | None = None,
) -> AnswerQualityResponse:
    selected_source_ids = [candidate.source_id for candidate in selected_candidates]
    if answer_result is None:
        return AnswerQualityResponse(
            answer_valid=True,
            citation_errors=[],
            selected_source_ids=selected_source_ids,
            cited_source_ids=[],
            cannot_confirm_reason=cannot_confirm_reason,
        )

    return AnswerQualityResponse(
        answer_valid=answer_result.valid,
        citation_errors=list(answer_result.citation_errors),
        selected_source_ids=selected_source_ids,
        cited_source_ids=[source.source_id for source in answer_result.sources],
        cannot_confirm_reason=answer_result.cannot_confirm_reason
        or cannot_confirm_reason,
    )


def _chat_stream_response_events(
    *,
    payload: ChatRequest,
    request: Request,
    session: Session,
    principal: SourcePrincipal,
) -> Iterator[dict[str, str]]:
    try:
        yield from _unsafe_chat_stream_response_events(
            payload=payload,
            request=request,
            session=session,
            principal=principal,
        )
    except HTTPException as error:
        mark_stream_error(request, error, detail=str(error.detail))
        session.rollback()
        yield {"event": "error", "data": _event_json({"detail": error.detail})}
    except Exception as error:
        mark_stream_error(request, error, detail="Chat stream failed.")
        session.rollback()
        yield {"event": "error", "data": _event_json({"detail": "Chat stream failed."})}


def _unsafe_chat_stream_response_events(
    *,
    payload: ChatRequest,
    request: Request,
    session: Session,
    principal: SourcePrincipal,
) -> Iterator[dict[str, str]]:
    started_at = perf_counter()
    conversation = _conversation_for_request(payload, session)
    user_message = Message(
        conversation=conversation,
        role="user",
        content=payload.query,
    )
    session.add(user_message)
    session.flush()

    if not index_is_ready(session):
        retrieval_diagnostics = _empty_retrieval_diagnostics(payload)
        answer_quality = _answer_quality_response(
            selected_candidates=[],
            answer_result=None,
            cannot_confirm_reason="not_indexed",
        )
        response = _persist_chat_response(
            session=session,
            conversation=conversation,
            user_message=user_message,
            query=payload.query,
            strategy=payload.strategy,
            answer=NOT_INDEXED_ANSWER,
            decision="cannot_confirm",
            selected_candidates=[],
            cited_candidates=[],
            retrieval_diagnostics=retrieval_diagnostics,
            answer_quality=answer_quality,
            latency_ms=_elapsed_ms(started_at),
            provider_calls=[],
        )
        yield from _chat_response_events(response)
        return

    retriever = HybridRetriever(
        session=session,
        embedding_provider=get_embedding_provider(request),
        visibility_labels=visibility_labels_for_principal(principal),
        score_threshold=API_RETRIEVAL_SCORE_THRESHOLD,
    )
    retrieval_result = retriever.search(
        payload.query,
        strategy=payload.strategy,
        limit=payload.limit,
    )
    selected_source_responses = [
        candidate_response(candidate) for candidate in retrieval_result.candidates
    ]
    yield _sources_event(
        sources=[],
        selected_sources=selected_source_responses,
        retrieval_diagnostics=retrieval_diagnostics_response(retrieval_result.diagnostics),
    )

    _raise_if_provider_budget_blocked(request)
    yield from _stream_answer_response_events(
        provider=get_answer_provider(request),
        payload=payload,
        request=request,
        session=session,
        conversation=conversation,
        user_message=user_message,
        retrieval_result=retrieval_result,
        started_at=started_at,
    )


def _stream_answer_response_events(
    *,
    provider: AnswerProvider,
    payload: ChatRequest,
    request: Request,
    session: Session,
    conversation: Conversation,
    user_message: Message,
    retrieval_result: RetrievalResult,
    started_at: float,
) -> Iterator[dict[str, str]]:
    answer_service = AnswerService(
        provider,
        client_request_id=_request_id_from_request(request),
    )
    answer_parts: list[str] = []

    try:
        for token in answer_service.stream_answer(payload.query, retrieval_result.candidates):
            answer_parts.append(token)
            yield {"event": "token", "data": token}
        generated_answer = "".join(answer_parts).strip() or CANNOT_CONFIRM_ANSWER
        answer_result = answer_service.validate_generated_answer(
            generated_answer,
            retrieval_result.candidates,
        )
    except Exception as error:
        _record_provider_call_records(request, answer_service.provider_call_records())
        raise HTTPException(status_code=502, detail="Answer provider failed.") from error
    _record_provider_call_records(request, answer_service.provider_call_records())

    cited_source_ids = {source.source_id for source in answer_result.sources}
    cited_candidates = [
        candidate
        for candidate in retrieval_result.candidates
        if candidate.source_id in cited_source_ids
    ]
    answer_quality = _answer_quality_response(
        selected_candidates=retrieval_result.candidates,
        answer_result=answer_result,
    )
    response = _persist_chat_response(
        session=session,
        conversation=conversation,
        user_message=user_message,
        query=payload.query,
        strategy=payload.strategy,
        answer=answer_result.answer,
        decision=_chat_decision(retrieval_result.decision, answer_result),
        selected_candidates=retrieval_result.candidates,
        cited_candidates=cited_candidates,
        retrieval_diagnostics=retrieval_result.diagnostics,
        answer_quality=answer_quality,
        latency_ms=_elapsed_ms(started_at),
        provider_calls=answer_result.provider_calls,
    )
    yield _done_event(response)


def _validate_stream_request(*, payload: ChatRequest, session: Session) -> None:
    if payload.conversation_id is None:
        return
    if session.get(Conversation, payload.conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")


def _chat_response_events(response: ChatResponse) -> Iterator[dict[str, str]]:
    yield _sources_event(
        sources=response.sources,
        selected_sources=response.selected_sources,
        retrieval_diagnostics=response.retrieval_diagnostics,
    )
    for token in _answer_token_chunks(response.answer):
        yield {"event": "token", "data": token}
    yield _done_event(response)


def _sources_event(
    *,
    sources: list[CandidateResponse],
    selected_sources: list[CandidateResponse],
    retrieval_diagnostics: RetrievalDiagnosticsResponse,
) -> dict[str, str]:
    return {
        "event": "sources",
        "data": _event_json(
            {
                "sources": _responses_to_json(sources),
                "selected_sources": _responses_to_json(selected_sources),
                "retrieval_diagnostics": retrieval_diagnostics.model_dump(mode="json"),
            }
        ),
    }


def _done_event(response: ChatResponse) -> dict[str, str]:
    return {
        "event": "done",
        "data": _event_json(
            {
                "conversation_id": str(response.conversation_id),
                "user_message_id": str(response.user_message_id),
                "assistant_message_id": str(response.assistant_message_id),
                "retrieval_event_id": str(response.retrieval_event_id),
                "answer": response.answer,
                "decision": response.decision,
                "answer_quality": response.answer_quality.model_dump(mode="json"),
            }
        ),
    }


def _answer_token_chunks(answer: str, *, chunk_size: int = 12) -> Iterator[str]:
    if not answer:
        yield ""
        return

    for start in range(0, len(answer), chunk_size):
        yield answer[start : start + chunk_size]


def _event_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _conversation_for_request(payload: ChatRequest, session: Session) -> Conversation:
    if payload.conversation_id is None:
        conversation = Conversation(title=payload.query[:80])
        session.add(conversation)
        session.flush()
        return conversation

    existing_conversation = session.get(Conversation, payload.conversation_id)
    if existing_conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return existing_conversation


def _persist_chat_response(
    *,
    session: Session,
    conversation: Conversation,
    user_message: Message,
    query: str,
    strategy: RetrievalStrategy,
    answer: str,
    decision: RetrievalDecision,
    selected_candidates: list[RetrievedCandidate],
    cited_candidates: list[RetrievedCandidate],
    retrieval_diagnostics: RetrievalDiagnostics,
    answer_quality: AnswerQualityResponse,
    latency_ms: int,
    provider_calls: list[dict[str, object]],
) -> ChatResponse:
    source_responses = [candidate_response(candidate) for candidate in cited_candidates]
    selected_source_responses = [
        candidate_response(candidate) for candidate in selected_candidates
    ]
    assistant_message = Message(
        conversation=conversation,
        role="assistant",
        content=answer,
        sources_json=_responses_to_json(source_responses),
    )
    session.add(assistant_message)
    session.flush()

    retrieval_event = RetrievalEvent(
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        query=query,
        strategy=strategy,
        selected_sources_json=_responses_to_json(selected_source_responses),
        scores_json=_retrieval_scores_payload(
            selected_candidates=selected_candidates,
            retrieval_diagnostics=retrieval_diagnostics,
            answer_quality=answer_quality,
            provider_calls=provider_calls,
        ),
        decision=decision,
        latency_ms=latency_ms,
    )
    session.add(retrieval_event)
    session.commit()

    return ChatResponse(
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        retrieval_event_id=retrieval_event.id,
        answer=answer,
        decision=decision,
        sources=source_responses,
        selected_sources=selected_source_responses,
        retrieval_diagnostics=retrieval_diagnostics_response(retrieval_diagnostics),
        answer_quality=answer_quality,
    )


def _responses_to_json(responses: list[CandidateResponse]) -> list[dict[str, Any]]:
    return [response.model_dump(mode="json") for response in responses]


def _retrieval_scores_payload(
    *,
    selected_candidates: list[RetrievedCandidate],
    retrieval_diagnostics: RetrievalDiagnostics,
    answer_quality: AnswerQualityResponse,
    provider_calls: list[dict[str, object]],
) -> dict[str, Any]:
    return {
        "scores_by_source_id": {
            candidate.source_id: candidate.score for candidate in selected_candidates
        },
        "retrieval_diagnostics": retrieval_diagnostics_response(
            retrieval_diagnostics
        ).model_dump(mode="json"),
        "answer_quality": answer_quality.model_dump(mode="json"),
        "provider_calls": provider_calls,
    }


def _request_id_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else None


def _record_provider_call_records(
    request: Request | None,
    records: list[ProviderCallRecord],
) -> None:
    if request is None or not records:
        return
    metrics = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics, InMemoryMetrics):
        metrics = InMemoryMetrics()
        request.app.state.metrics = metrics
    for record in records:
        metrics.record_provider_call(record)


def _raise_if_provider_budget_blocked(request: Request) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics, InMemoryMetrics):
        metrics = InMemoryMetrics()
        request.app.state.metrics = metrics
    exception = _provider_budget_block_exception(
        settings=get_app_settings(request),
        metrics_snapshot=metrics.snapshot(),
    )
    if exception is not None:
        raise exception


def _provider_budget_block_exception(
    *,
    settings: Settings,
    metrics_snapshot: dict[str, Any],
) -> HTTPException | None:
    budget = provider_budget_status(
        settings,
        metrics_snapshot=metrics_snapshot,
    )
    if not budget.should_block:
        return None
    return HTTPException(status_code=429, detail=PROVIDER_BUDGET_EXCEEDED_DETAIL)


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
