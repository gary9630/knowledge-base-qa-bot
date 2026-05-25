from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.answer.citations import CANNOT_CONFIRM_ANSWER
from app.answer.service import AnswerResult
from app.api.chat import (
    NOT_INDEXED_ANSWER,
    ChatRequest,
    ChatResponse,
    _chat_decision,
    _chat_response_events,
    _validate_stream_request,
)


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
    )

    events = list(_chat_response_events(response))

    assert [event["event"] for event in events] == ["sources", "token", "token", "done"]
    assert json.loads(events[0]["data"]) == {"sources": [], "selected_sources": []}
    assert "".join(event["data"] for event in events[1:-1]) == NOT_INDEXED_ANSWER
    done_payload = json.loads(events[-1]["data"])
    assert done_payload["decision"] == "cannot_confirm"
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
