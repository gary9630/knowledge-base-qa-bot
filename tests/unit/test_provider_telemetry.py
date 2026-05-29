from app.observability.metrics import InMemoryMetrics
from app.provider_telemetry import ProviderCallRecord, ProviderUsage


def test_metrics_tracks_provider_usage_and_errors() -> None:
    metrics = InMemoryMetrics()
    metrics.record_provider_call(
        ProviderCallRecord(
            provider="openai",
            operation="chat.completions",
            model="gpt-test",
            status="succeeded",
            client_request_id="request-1-1",
            provider_request_id="chatcmpl-request",
            usage=ProviderUsage(
                prompt_tokens=20,
                completion_tokens=5,
                total_tokens=25,
                cached_tokens=3,
                reasoning_tokens=2,
            ),
            usage_complete=True,
            latency_ms=123,
        )
    )
    metrics.record_provider_call(
        ProviderCallRecord(
            provider="openai",
            operation="chat.completions.stream",
            model="gpt-test",
            status="failed",
            client_request_id="request-2-1",
            error_type="APITimeoutError",
            usage_complete=False,
            latency_ms=456,
        )
    )

    snapshot = metrics.snapshot()

    assert snapshot["provider_calls_total"] == 2
    assert snapshot["provider_errors_total"] == 1
    assert snapshot["provider_calls_by_key"] == {
        "openai:gpt-test:chat.completions": 1,
        "openai:gpt-test:chat.completions.stream": 1,
    }
    assert snapshot["provider_usage_by_key"]["openai:gpt-test:chat.completions"] == {
        "prompt_tokens": 20,
        "completion_tokens": 5,
        "total_tokens": 25,
        "cached_tokens": 3,
        "reasoning_tokens": 2,
    }
    assert snapshot["latest_provider_calls"][0]["status"] == "failed"
    assert snapshot["latest_provider_calls"][0]["error_type"] == "APITimeoutError"
