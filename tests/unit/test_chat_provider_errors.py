from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.answer.providers import AnswerSource
from app.api.chat import (
    ChatRequest,
    _answer_provider_error_response,
    _provider_budget_block_exception,
)
from app.core.config import Settings
from app.retrieval.models import RetrievedCandidate


class FailingAnswerProvider:
    def generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> str:
        raise RuntimeError("upstream timeout")


def test_answer_provider_error_maps_to_stable_http_exception() -> None:
    payload = ChatRequest(query="Where is the course site?")
    candidate = RetrievedCandidate(
        section_id=uuid4(),
        source_id="faq.md#course-site",
        filename="faq.md",
        heading="Course Site",
        body_md="The course site is on the platform homepage.",
        score=0.8,
        strategy="hybrid",
    )

    with pytest.raises(HTTPException) as exc_info:
        _answer_provider_error_response(
            provider=FailingAnswerProvider(),
            payload=payload,
            candidates=[candidate],
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Answer provider failed."


def test_provider_budget_block_exception_maps_to_stable_http_429() -> None:
    exception = _provider_budget_block_exception(
        settings=Settings(
            provider_budget_daily_call_limit=1,
            provider_budget_block_on_exceeded=True,
        ),
        metrics_snapshot={
            "provider_calls_total": 1,
            "provider_errors_total": 0,
            "provider_usage_by_key": {},
        },
    )

    assert exception is not None
    assert exception.status_code == 429
    assert exception.detail == "Provider budget exceeded."
