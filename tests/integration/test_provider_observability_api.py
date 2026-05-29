from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.tables import Conversation, Message, RetrievalEvent
from app.observability.metrics import InMemoryMetrics
from app.provider_telemetry import ProviderCallRecord, ProviderUsage


def test_provider_observability_requires_admin_key(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_provider_observability_app(db_session, tmp_path))

    unauthorized_response = client.get("/admin/provider-observability")
    authorized_response = client.get(
        "/admin/provider-observability",
        headers={"X-KB-Admin-Key": "secret"},
    )

    assert unauthorized_response.status_code == 401
    assert authorized_response.status_code == 200


def test_provider_observability_returns_metrics_and_db_traces(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _provider_observability_app(db_session, tmp_path)
    app.state.metrics.record_provider_call(
        ProviderCallRecord(
            provider="openai",
            operation="chat.completions.stream",
            model="gpt-test",
            status="succeeded",
            client_request_id="request-1-1",
            usage=ProviderUsage(prompt_tokens=30, completion_tokens=6, total_tokens=36),
            usage_complete=True,
            latency_ms=123,
        )
    )
    retrieval_event = _provider_retrieval_event(db_session)
    client = TestClient(app)

    response = client.get(
        "/admin/provider-observability",
        headers={"X-KB-Admin-Key": "secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_calls"] == 1
    assert body["summary"]["total_tokens"] == 36
    assert body["budget"]["status"] == "exceeded"
    assert body["budget"]["should_block"] is True
    assert body["usage_by_key"][0]["key"] == "openai:gpt-test:chat.completions.stream"
    assert body["latest_calls"][0]["client_request_id"] == "request-1-1"
    assert body["traces"][0]["retrieval_event_id"] == str(retrieval_event.id)
    assert body["traces"][0]["provider_calls"][0]["usage"]["total_tokens"] == 12


def _provider_observability_app(db_session: Session, tmp_path: Path) -> FastAPI:
    docs_dir = tmp_path / "docs"
    raw_dir = tmp_path / "raw"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    settings = Settings(
        docs_dir=str(docs_dir),
        raw_dir=str(raw_dir),
        kb_dir=str(kb_dir),
        embedding_provider="fake",
        answer_provider="fake",
        admin_api_key="secret",
        provider_budget_daily_token_limit=36,
        provider_budget_block_on_exceeded=True,
    )
    app = create_app(settings=settings, session_factory=lambda: db_session)
    app.state.metrics = InMemoryMetrics()
    return app


def _provider_retrieval_event(db_session: Session) -> RetrievalEvent:
    conversation = Conversation(id=uuid4(), title="provider trace")
    message = Message(
        id=uuid4(),
        conversation=conversation,
        role="assistant",
        content="answer",
    )
    db_session.add_all([conversation, message])
    db_session.flush()

    retrieval_event = RetrievalEvent(
        id=uuid4(),
        conversation_id=conversation.id,
        message_id=message.id,
        query="Where?",
        strategy="hybrid",
        selected_sources_json=[],
        scores_json={
            "provider_calls": [
                {
                    "provider": "openai",
                    "operation": "chat.completions",
                    "model": "gpt-test",
                    "status": "succeeded",
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                        "cached_tokens": 0,
                        "reasoning_tokens": 0,
                    },
                    "usage_complete": True,
                }
            ]
        },
        decision="can_answer",
        latency_ms=11,
    )
    db_session.add(retrieval_event)
    db_session.commit()
    return retrieval_event
