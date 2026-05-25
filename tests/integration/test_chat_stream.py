from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app


@dataclass(frozen=True)
class IndexedSampleDocsApp:
    app: FastAPI
    test_client: TestClient


@pytest.fixture
def app_with_indexed_sample_docs(
    db_session: Session,
    tmp_path: Path,
) -> IndexedSampleDocsApp:
    docs_dir = tmp_path / "docs"
    raw_dir = tmp_path / "raw"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    (docs_dir / "常見問題FAQ.md").write_text(
        "# FAQ\n\n"
        "## 課程網站\n\n"
        "課程網站是 https://buildmoat.org/\n\n"
        "## 作業繳交\n\n"
        "請依公告時間繳交作業。\n",
        encoding="utf-8",
    )

    settings = Settings(
        docs_dir=str(docs_dir),
        raw_dir=str(raw_dir),
        kb_dir=str(kb_dir),
        embedding_provider="fake",
        answer_provider="fake",
    )
    app = create_app(settings=settings, session_factory=_session_factory(db_session))
    client = TestClient(app)

    index_response = client.post("/index")
    assert index_response.status_code == 200
    assert index_response.json()["status"] == "succeeded"

    return IndexedSampleDocsApp(app=app, test_client=client)


def test_chat_stream_validates_request_payload() -> None:
    app = create_app(
        settings=Settings(
            embedding_provider="fake",
            answer_provider="fake",
        )
    )
    client = TestClient(app)

    response = client.post("/chat/stream", json={})

    assert response.status_code == 422


def test_chat_stream_sends_sources_tokens_and_done(
    app_with_indexed_sample_docs: IndexedSampleDocsApp,
) -> None:
    client = app_with_indexed_sample_docs.test_client

    with client.stream("POST", "/chat/stream", json={"query": "課程網站在哪？"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = _parse_sse_events(body)
    event_names = [event["event"] for event in events]
    assert event_names[0] == "sources"
    assert event_names[-1] == "done"
    assert event_names[1:-1]
    assert all(name == "token" for name in event_names[1:-1])

    sources_payload = json.loads(events[0]["data"])
    assert sources_payload["sources"][0]["source_id"] == "常見問題FAQ.md#課程網站"
    assert sources_payload["selected_sources"][0]["source_id"] == "常見問題FAQ.md#課程網站"

    token_data = [event["data"] for event in events[1:-1]]
    assert all(len(token) == 12 for token in token_data[:-1])
    streamed_answer = "".join(token_data)
    assert "常見問題FAQ.md#課程網站" in streamed_answer

    done_payload = json.loads(events[-1]["data"])
    assert done_payload["decision"] == "can_answer"
    assert UUID(done_payload["conversation_id"])
    assert UUID(done_payload["user_message_id"])
    assert UUID(done_payload["assistant_message_id"])
    assert UUID(done_payload["retrieval_event_id"])


def test_parse_sse_events_supports_crlf_frames() -> None:
    body = 'event: sources\r\ndata: {"sources":[]}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n'

    assert _parse_sse_events(body) == [
        {"event": "sources", "data": '{"sources":[]}'},
        {"event": "done", "data": "{}"},
    ]


def _parse_sse_events(body: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    normalized_body = body.replace("\r\n", "\n")
    for frame in normalized_body.strip().split("\n\n"):
        event: dict[str, str] = {}
        for line in frame.splitlines():
            if line.startswith("event: "):
                event["event"] = line.removeprefix("event: ")
            if line.startswith("data: "):
                event["data"] = line.removeprefix("data: ")
        if event:
            events.append(event)
    return events


def _session_factory(db_session: Session) -> Callable[[], Session]:
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return create_session
