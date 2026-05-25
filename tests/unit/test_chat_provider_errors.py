from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.answer.providers import AnswerSource
from app.api.chat import ChatRequest, _answer_provider_error_response
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
