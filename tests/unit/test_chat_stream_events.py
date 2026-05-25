from __future__ import annotations

import json
from uuid import uuid4

from app.api.chat import (
    NOT_INDEXED_ANSWER,
    ChatResponse,
    _chat_response_events,
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
