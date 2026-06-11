from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.answer.providers import AnswerSource
from app.core.config import Settings
from app.main import create_app
from app.observability.middleware import REQUEST_LOGGER_NAME
from app.provider_telemetry import ProviderCallRecord


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


def test_chat_stream_missing_conversation_returns_404(db_session: Session) -> None:
    app = create_app(
        settings=Settings(
            embedding_provider="fake",
            answer_provider="fake",
        ),
        session_factory=_session_factory(db_session),
    )
    client = TestClient(app)

    response = client.post(
        "/chat/stream",
        json={
            "query": "課程網站在哪？",
            "conversation_id": "00000000-0000-0000-0000-000000000001",
        },
    )

    assert response.status_code == 404


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
    assert sources_payload["sources"] == []
    assert sources_payload["selected_sources"][0]["source_id"] == "常見問題FAQ.md#課程網站"
    assert sources_payload["retrieval_diagnostics"]["accepted_count"] >= 1
    assert sources_payload["retrieval_diagnostics"]["selected_source_ids"][0] == (
        "常見問題FAQ.md#課程網站"
    )

    token_data = [event["data"] for event in events[1:-1]]
    assert all(len(token) == 12 for token in token_data[:-1])
    streamed_answer = "".join(token_data)
    assert "常見問題FAQ.md#課程網站" in streamed_answer

    done_payload = json.loads(events[-1]["data"])
    assert done_payload["decision"] == "can_answer"
    assert done_payload["answer_quality"]["answer_valid"] is True
    assert done_payload["answer_quality"]["cited_source_ids"] == ["常見問題FAQ.md#課程網站"]
    assert done_payload["context_assembly"] is not None
    assert done_payload["context_assembly"]["hit_count"] >= 1
    assert done_payload["sources"]
    assert done_payload["sources"][0]["source_id"] == "常見問題FAQ.md#課程網站"
    assert UUID(done_payload["conversation_id"])
    assert UUID(done_payload["user_message_id"])
    assert UUID(done_payload["assistant_message_id"])
    assert UUID(done_payload["retrieval_event_id"])


def test_chat_stream_provider_error_records_stream_failure(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    raw_dir = tmp_path / "raw"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    (docs_dir / "faq.md").write_text(
        "# FAQ\n\n## Course Site\n\nCourse site is https://buildmoat.org/\n",
        encoding="utf-8",
    )
    app = create_app(
        settings=Settings(
            docs_dir=str(docs_dir),
            raw_dir=str(raw_dir),
            kb_dir=str(kb_dir),
            embedding_provider="fake",
            answer_provider="fake",
        ),
        session_factory=_session_factory(db_session),
        answer_provider=FailingAnswerProvider(),
    )
    client = TestClient(app)
    index_response = client.post("/index")
    assert index_response.status_code == 200

    with _captured_request_logs(logging.ERROR) as records:
        with client.stream(
            "POST",
            "/chat/stream",
            json={"query": "Where is the course site?"},
            headers={"X-Request-ID": "chat-stream-error"},
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    metrics = app.state.metrics.snapshot()
    log_payloads = [_json_log(record.message) for record in records]
    events = _parse_sse_events(body)

    assert events[-1]["event"] == "error"
    assert metrics["errors_total"] == 1
    assert metrics["latest_requests"][0]["request_id"] == "chat-stream-error"
    assert metrics["latest_requests"][0]["route"] == "POST /chat/stream"
    assert log_payloads[0]["event"] == "request_failed"
    assert log_payloads[0]["request_id"] == "chat-stream-error"
    assert log_payloads[0]["stream_error"] is True
    assert log_payloads[0]["handled"] is True
    assert log_payloads[0]["error"] == "HTTPException"


def test_chat_stream_provider_budget_block_returns_stable_error(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    raw_dir = tmp_path / "raw"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    (docs_dir / "faq.md").write_text(
        "# FAQ\n\n## Course Site\n\nCourse site is https://buildmoat.org/\n",
        encoding="utf-8",
    )
    answer_provider = TrackingStreamingAnswerProvider()
    app = create_app(
        settings=Settings(
            docs_dir=str(docs_dir),
            raw_dir=str(raw_dir),
            kb_dir=str(kb_dir),
            embedding_provider="fake",
            answer_provider="fake",
            provider_budget_daily_call_limit=1,
            provider_budget_block_on_exceeded=True,
        ),
        session_factory=_session_factory(db_session),
        answer_provider=answer_provider,
    )
    client = TestClient(app)
    index_response = client.post("/index")
    app.state.metrics.record_provider_call(
        ProviderCallRecord(
            provider="openai",
            operation="chat.completions.stream",
            model="gpt-test",
            status="succeeded",
        )
    )

    with client.stream(
        "POST",
        "/chat/stream",
        json={"query": "Where is the course site?"},
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse_events(body)

    assert index_response.status_code == 200
    assert response.status_code == 200
    assert events[-1]["event"] == "error"
    assert json.loads(events[-1]["data"])["detail"] == "Provider budget exceeded."
    assert answer_provider.calls == 0


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


class FailingAnswerProvider:
    def generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> str:
        raise RuntimeError("answer provider failed")


class TrackingStreamingAnswerProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> str:
        self.calls += 1
        return "Course site is https://buildmoat.org/ [faq.md#course-site]"

    def stream_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> Iterator[str]:
        self.calls += 1
        yield "Course site is https://buildmoat.org/ [faq.md#course-site]"


class _ListHandler(logging.Handler):
    def __init__(self, level: int) -> None:
        super().__init__(level)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _captured_request_logs(level: int) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger(REQUEST_LOGGER_NAME)
    handler = _ListHandler(level)
    previous_level = logger.level
    previous_disabled = logger.disabled
    previous_global_disable = logging.root.manager.disable
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.disabled = False
    logging.disable(logging.NOTSET)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.disabled = previous_disabled
        logging.disable(previous_global_disable)


def _json_log(message: str) -> dict[str, object]:
    payload = json.loads(message)
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _session_factory(db_session: Session) -> Callable[[], Session]:
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return create_session
