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
    get_embedding_provider,
    get_request_db_session,
)
from app.api.indexing import index_is_ready
from app.api.search import (
    API_RETRIEVAL_SCORE_THRESHOLD,
    CandidateResponse,
    candidate_response,
)
from app.models.tables import Conversation, Message, RetrievalEvent
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.models import RetrievalDecision, RetrievalStrategy, RetrievedCandidate

router = APIRouter()

NOT_INDEXED_ANSWER = "知識庫尚未建立索引，請先建立索引。"


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    conversation_id: UUID | None = None
    strategy: RetrievalStrategy = "hybrid"
    limit: int = Field(default=5, ge=1, le=20)


class ChatResponse(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    retrieval_event_id: UUID
    answer: str
    decision: RetrievalDecision
    sources: list[CandidateResponse]
    selected_sources: list[CandidateResponse]


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> ChatResponse:
    return _build_chat_response(payload=payload, request=request, session=session)


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> EventSourceResponse:
    _validate_stream_request(payload=payload, session=session)
    return EventSourceResponse(
        _chat_stream_response_events(payload=payload, request=request, session=session)
    )


def _build_chat_response(
    *,
    payload: ChatRequest,
    request: Request,
    session: Session,
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
            latency_ms=_elapsed_ms(started_at),
        )

    retriever = HybridRetriever(
        session=session,
        embedding_provider=get_embedding_provider(request),
        score_threshold=API_RETRIEVAL_SCORE_THRESHOLD,
    )
    retrieval_result = retriever.search(
        payload.query,
        strategy=payload.strategy,
        limit=payload.limit,
    )
    answer_result = _answer_provider_error_response(
        provider=get_answer_provider(request),
        payload=payload,
        candidates=retrieval_result.candidates,
    )
    cited_source_ids = {source.source_id for source in answer_result.sources}
    cited_candidates = [
        candidate
        for candidate in retrieval_result.candidates
        if candidate.source_id in cited_source_ids
    ]

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
        latency_ms=_elapsed_ms(started_at),
    )


def _answer_provider_error_response(
    *,
    provider: AnswerProvider,
    payload: ChatRequest,
    candidates: list[RetrievedCandidate],
) -> AnswerResult:
    try:
        return AnswerService(provider).answer(payload.query, candidates)
    except Exception as error:
        raise HTTPException(status_code=502, detail="Answer provider failed.") from error


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


def _chat_stream_response_events(
    *,
    payload: ChatRequest,
    request: Request,
    session: Session,
) -> Iterator[dict[str, str]]:
    try:
        yield from _unsafe_chat_stream_response_events(
            payload=payload,
            request=request,
            session=session,
        )
    except HTTPException as error:
        session.rollback()
        yield {"event": "error", "data": _event_json({"detail": error.detail})}
    except Exception:
        session.rollback()
        yield {"event": "error", "data": _event_json({"detail": "Chat stream failed."})}


def _unsafe_chat_stream_response_events(
    *,
    payload: ChatRequest,
    request: Request,
    session: Session,
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
            latency_ms=_elapsed_ms(started_at),
        )
        yield from _chat_response_events(response)
        return

    retriever = HybridRetriever(
        session=session,
        embedding_provider=get_embedding_provider(request),
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
    yield _sources_event(sources=[], selected_sources=selected_source_responses)

    answer_result = _answer_provider_error_response(
        provider=get_answer_provider(request),
        payload=payload,
        candidates=retrieval_result.candidates,
    )

    cited_source_ids = {source.source_id for source in answer_result.sources}
    cited_candidates = [
        candidate
        for candidate in retrieval_result.candidates
        if candidate.source_id in cited_source_ids
    ]
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
        latency_ms=_elapsed_ms(started_at),
    )

    for token in _answer_token_chunks(response.answer):
        yield {"event": "token", "data": token}
    yield _done_event(response)


def _validate_stream_request(*, payload: ChatRequest, session: Session) -> None:
    if payload.conversation_id is None:
        return
    if session.get(Conversation, payload.conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")


def _chat_response_events(response: ChatResponse) -> Iterator[dict[str, str]]:
    yield _sources_event(sources=response.sources, selected_sources=response.selected_sources)
    for token in _answer_token_chunks(response.answer):
        yield {"event": "token", "data": token}
    yield _done_event(response)


def _sources_event(
    *,
    sources: list[CandidateResponse],
    selected_sources: list[CandidateResponse],
) -> dict[str, str]:
    return {
        "event": "sources",
        "data": _event_json(
            {
                "sources": _responses_to_json(sources),
                "selected_sources": _responses_to_json(selected_sources),
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
                "decision": response.decision,
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
    latency_ms: int,
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
        scores_json={
            candidate.source_id: candidate.score for candidate in selected_candidates
        },
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
    )


def _responses_to_json(responses: list[CandidateResponse]) -> list[dict[str, Any]]:
    return [response.model_dump(mode="json") for response in responses]


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
