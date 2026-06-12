from __future__ import annotations

import json
from typing import Any

from app.answer.query_router import (
    BLOCKED_ANSWER,
    AllowAllQueryRouter,
    OpenAIQueryRouter,
    QueryRouteDecision,
    StaticQueryRouter,
    create_query_router,
    hard_answer_model,
)
from app.core.config import Settings
from app.provider_telemetry import ProviderCallContext


class _FakeCompletions:
    def __init__(self, content: str | Exception) -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self._content, Exception):
            raise self._content

        class _Message:
            content = self._content

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]
            usage = None
            id = "resp-router-1"

        return _Response()


class _FakeClient:
    def __init__(self, content: str | Exception) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})()


def _settings(**kwargs: object) -> Settings:
    base: dict[str, object] = {
        "embedding_provider": "fake",
        "answer_provider": "fake",
    }
    base.update(kwargs)
    return Settings(**base)


def test_blocked_answer_copy_matches_spec() -> None:
    assert BLOCKED_ANSWER == "這個問題和學習無關，Let's learn together!"


def test_openai_router_routes_course_question_with_difficulty() -> None:
    router_output = json.dumps(
        {"category": "course", "difficulty": "hard", "reason": "multi-concept"}
    )
    client = _FakeClient(router_output)
    router = OpenAIQueryRouter(client=client)
    context = ProviderCallContext(client_request_id="req-1")

    decision = router.route("如何設計一個高可用的快取層？", context=context)

    assert decision.allowed is True
    assert decision.category == "course"
    assert decision.difficulty == "hard"
    # the router call is recorded with request/response payloads for the audit log
    assert len(context.records) == 1
    record = context.records[0]
    assert record.operation == "chat.completions.router"
    assert record.status == "succeeded"
    assert record.request_payload is not None
    assert "messages" in record.request_payload
    assert record.response_payload == {"content": router_output}


def test_openai_router_blocks_off_topic_harmful_and_injection() -> None:
    for category in ("off_topic", "harmful", "prompt_injection"):
        client = _FakeClient(json.dumps({"category": category, "difficulty": "easy"}))
        router = OpenAIQueryRouter(client=client)

        decision = router.route("今天天氣如何？")

        assert decision.allowed is False, category
        assert decision.category == category


def test_openai_router_fails_open_on_provider_error() -> None:
    client = _FakeClient(RuntimeError("router down"))
    router = OpenAIQueryRouter(client=client)
    context = ProviderCallContext(client_request_id="req-2")

    decision = router.route("什麼是 CAP theorem？", context=context)

    assert decision.allowed is True
    assert decision.router_failed is True
    assert decision.difficulty == "easy"
    assert context.records[0].status == "failed"


def test_openai_router_fails_open_on_unparseable_output() -> None:
    client = _FakeClient("not json at all")
    router = OpenAIQueryRouter(client=client)

    decision = router.route("什麼是 sharding？")

    assert decision.allowed is True
    assert decision.router_failed is True


def test_openai_router_normalizes_unknown_categories() -> None:
    client = _FakeClient(json.dumps({"category": "weird", "difficulty": "extreme"}))
    router = OpenAIQueryRouter(client=client)

    decision = router.route("query")

    assert decision.category == "course"
    assert decision.difficulty == "easy"


def test_create_query_router_for_fake_provider_allows_everything() -> None:
    router = create_query_router(_settings())
    assert isinstance(router, AllowAllQueryRouter)
    assert router.route("anything").allowed is True


def test_create_query_router_respects_disable_flag() -> None:
    router = create_query_router(_settings(answer_provider="openai", query_router_enabled=False))
    assert isinstance(router, AllowAllQueryRouter)


def test_create_query_router_uses_openai_router_for_openai_provider() -> None:
    router = create_query_router(
        _settings(
            answer_provider="openai",
            openai_api_key="sk-test",
            openai_router_model="gpt-router-test",
        )
    )
    assert isinstance(router, OpenAIQueryRouter)
    assert router.model == "gpt-router-test"


def test_router_default_model_is_mini() -> None:
    router = OpenAIQueryRouter(client=_FakeClient("{}"))
    assert router.model == "gpt-5.4-mini"


def test_hard_answer_model_defaults_to_full_model() -> None:
    assert hard_answer_model(_settings()) == "gpt-5.4"
    assert hard_answer_model(_settings(openai_chat_model_hard="gpt-custom")) == "gpt-custom"


def test_static_query_router_pops_queued_decisions() -> None:
    router = StaticQueryRouter([QueryRouteDecision(category="off_topic")])

    first = router.route("天氣如何")
    second = router.route("什麼是 cache")

    assert first.allowed is False
    assert second.allowed is True
    assert router.queries == ["天氣如何", "什麼是 cache"]
