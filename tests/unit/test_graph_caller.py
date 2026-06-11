from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.graph.pipeline import GRAPH_EXTRACTION_OPERATION, OpenAIGraphCaller
from app.provider_telemetry import ProviderCallContext, ProviderUsage


class _StubCompletions:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _StubClient:
    def __init__(self, outcome: object) -> None:
        self.completions = _StubCompletions(outcome)
        self.chat = SimpleNamespace(completions=self.completions)


def _response(content: object) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp-123",
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_tokens_details=SimpleNamespace(cached_tokens=2),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=1),
        ),
    )


def _caller(outcome: object) -> tuple[OpenAIGraphCaller, _StubClient]:
    client = _StubClient(outcome)
    caller = OpenAIGraphCaller(
        model="gpt-test",
        client=client,
        context=ProviderCallContext(client_request_id="graph"),
    )
    return caller, client


def test_complete_returns_content_and_records_success() -> None:
    caller, client = _caller(_response('{"concepts": []}'))

    assert caller.complete(system="sys", user="usr") == '{"concepts": []}'

    [request] = client.completions.requests
    assert request["model"] == "gpt-test"
    assert request["response_format"] == {"type": "json_object"}
    [record] = caller.call_records
    assert record.operation == GRAPH_EXTRACTION_OPERATION
    assert record.status == "succeeded"
    assert record.provider_request_id == "resp-123"
    assert record.client_request_id == "graph-1"
    assert record.usage_complete is True
    assert record.usage == ProviderUsage(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cached_tokens=2,
        reasoning_tokens=1,
    )


@pytest.mark.parametrize("content", [None, "", 123])
def test_complete_raises_on_empty_or_non_string_content(content: object) -> None:
    caller, _ = _caller(_response(content))

    with pytest.raises(RuntimeError, match="graph extraction returned empty content"):
        caller.complete(system="sys", user="usr")

    [record] = caller.call_records
    assert record.operation == GRAPH_EXTRACTION_OPERATION
    assert record.status == "failed"
    assert record.error_type == "RuntimeError"
    # tokens were spent even though the content was unusable
    assert record.usage is not None


def test_complete_reraises_client_error_and_records_failure() -> None:
    caller, _ = _caller(ValueError("boom"))

    with pytest.raises(ValueError, match="boom"):
        caller.complete(system="sys", user="usr")

    [record] = caller.call_records
    assert record.operation == GRAPH_EXTRACTION_OPERATION
    assert record.status == "failed"
    assert record.error_type == "ValueError"
    assert record.usage is None


def test_constructor_requires_api_key_or_injected_client() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIGraphCaller(model="gpt-test")
