from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.answer.citations import CANNOT_CONFIRM_ANSWER
from app.answer.service import AnswerResult
from app.api.chat import (
    NOT_INDEXED_ANSWER,
    AnswerQualityResponse,
    ChatRequest,
    ChatResponse,
    _chat_decision,
    _chat_response_events,
    _retrieval_scores_payload,
    _validate_stream_request,
)
from app.api.search import RetrievalDiagnosticsResponse
from app.retrieval.models import RetrievalDiagnostics


def test_chat_stream_events_encode_not_indexed_response() -> None:
    response = ChatResponse(
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        retrieval_event_id=uuid4(),
        answer=NOT_INDEXED_ANSWER,
        decision="cannot_confirm",
        sources=[],
        selected_sources=[],
        retrieval_diagnostics=RetrievalDiagnosticsResponse(
            strategy="hybrid",
            requested_limit=5,
            score_threshold=0.05,
            raw_candidate_count=0,
            merged_candidate_count=0,
            accepted_count=0,
            rejected_count=0,
            top_score=None,
        ),
        answer_quality=AnswerQualityResponse(
            answer_valid=True,
            cannot_confirm_reason="not_indexed",
        ),
    )

    events = list(_chat_response_events(response))

    assert [event["event"] for event in events] == ["sources", "token", "token", "done"]
    sources_payload = json.loads(events[0]["data"])
    assert sources_payload["sources"] == []
    assert sources_payload["selected_sources"] == []
    assert sources_payload["retrieval_diagnostics"]["accepted_count"] == 0
    assert "".join(event["data"] for event in events[1:-1]) == NOT_INDEXED_ANSWER
    done_payload = json.loads(events[-1]["data"])
    assert done_payload["decision"] == "cannot_confirm"
    assert done_payload["answer"] == NOT_INDEXED_ANSWER
    assert done_payload["answer_quality"]["cannot_confirm_reason"] == "not_indexed"
    assert done_payload["conversation_id"] == str(response.conversation_id)


def test_chat_decision_downgrades_when_answer_cannot_confirm() -> None:
    answer_result = AnswerResult(answer=CANNOT_CONFIRM_ANSWER, sources=[], valid=False)

    assert _chat_decision("can_answer", answer_result) == "cannot_confirm"


def test_validate_stream_request_preserves_missing_conversation_404() -> None:
    class MissingConversationSession:
        def get(self, model: object, key: object) -> None:
            return None

    payload = ChatRequest(
        query="Where?",
        conversation_id=uuid4(),
    )

    with pytest.raises(HTTPException) as exc_info:
        _validate_stream_request(
            payload=payload,
            session=MissingConversationSession(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 404


def test_retrieval_scores_payload_includes_provider_calls() -> None:
    payload = _retrieval_scores_payload(
        selected_candidates=[],
        retrieval_diagnostics=RetrievalDiagnostics(
            strategy="hybrid",
            requested_limit=5,
            score_threshold=0.05,
        ),
        answer_quality=AnswerQualityResponse(answer_valid=True),
        provider_calls=[
            {
                "provider": "openai",
                "operation": "chat.completions.stream",
                "model": "gpt-test",
                "status": "succeeded",
                "usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 6,
                    "total_tokens": 36,
                    "cached_tokens": 4,
                    "reasoning_tokens": 1,
                },
                "usage_complete": True,
            }
        ],
    )

    assert payload["provider_calls"][0]["model"] == "gpt-test"
    assert payload["provider_calls"][0]["usage"]["total_tokens"] == 36
