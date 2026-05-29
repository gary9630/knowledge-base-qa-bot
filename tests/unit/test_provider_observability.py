from uuid import uuid4

from app.api.provider_observability import (
    provider_observability_response,
    provider_trace_response,
)
from app.models.tables import RetrievalEvent


def test_provider_observability_response_summarizes_metrics_snapshot() -> None:
    payload = provider_observability_response(
        metrics_snapshot={
            "provider_calls_total": 3,
            "provider_errors_total": 1,
            "provider_calls_by_key": {
                "openai:gpt-test:chat.completions.stream": 2,
                "openai:text-embedding-test:embeddings": 1,
            },
            "provider_usage_by_key": {
                "openai:gpt-test:chat.completions.stream": {
                    "prompt_tokens": 30,
                    "completion_tokens": 6,
                    "total_tokens": 36,
                    "cached_tokens": 4,
                    "reasoning_tokens": 1,
                }
            },
            "latest_provider_calls": [
                {
                    "provider": "openai",
                    "operation": "chat.completions.stream",
                    "model": "gpt-test",
                    "status": "failed",
                    "error_type": "APITimeoutError",
                    "usage_complete": False,
                    "latency_ms": 456,
                }
            ],
        },
        traces=[],
    )

    assert payload.summary.total_calls == 3
    assert payload.summary.error_rate == 1 / 3
    assert payload.summary.total_tokens == 36
    assert len(payload.usage_by_key) == 2
    assert payload.usage_by_key[0].key == "openai:gpt-test:chat.completions.stream"
    assert payload.usage_by_key[0].calls == 2
    assert payload.usage_by_key[1].key == "openai:text-embedding-test:embeddings"
    assert payload.usage_by_key[1].calls == 1
    assert payload.usage_by_key[1].usage.total_tokens == 0
    assert payload.latest_calls[0].error_type == "APITimeoutError"


def test_provider_trace_response_ignores_malformed_provider_calls() -> None:
    event = RetrievalEvent(
        id=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        query="課程網站在哪裡？",
        strategy="hybrid",
        selected_sources_json=[],
        scores_json={
            "provider_calls": [
                {
                    "provider": "openai",
                    "operation": "chat.completions.stream",
                    "model": "gpt-test",
                    "status": "succeeded",
                    "usage_complete": True,
                    "usage": {"total_tokens": 36},
                },
                {"provider": "openai"},
                "not-a-call",
            ]
        },
        decision="can_answer",
        latency_ms=123,
    )

    trace = provider_trace_response(event)

    assert trace is not None
    assert trace.retrieval_event_id == event.id
    assert trace.query == "課程網站在哪裡？"
    assert len(trace.provider_calls) == 1
    assert trace.provider_calls[0].usage is not None
    assert trace.provider_calls[0].usage.total_tokens == 36
