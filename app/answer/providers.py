from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.answer.citations import CANNOT_CONFIRM_ANSWER


@dataclass(frozen=True)
class AnswerSource:
    source_id: str
    filename: str
    heading: str
    body_md: str
    score: float | None = None


@dataclass(frozen=True)
class AnswerProviderCall:
    query: str
    source_ids: tuple[str, ...]
    strict: bool


class AnswerProvider(Protocol):
    def generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> str: ...


class FakeAnswerProvider:
    def __init__(self, answers: Sequence[str] | None = None) -> None:
        self._answers = list(answers or [])
        self.calls: list[AnswerProviderCall] = []

    def generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> str:
        self.calls.append(
            AnswerProviderCall(
                query=query,
                source_ids=tuple(source.source_id for source in sources),
                strict=strict,
            )
        )
        if not self._answers:
            return CANNOT_CONFIRM_ANSWER
        return self._answers.pop(0)


class OpenAIAnswerProvider:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model

    def generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> str:
        raise NotImplementedError("OpenAI answer generation is not implemented yet.")
