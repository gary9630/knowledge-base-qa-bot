from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, overload
from uuid import UUID

RetrievalDecision = Literal["can_answer", "cannot_confirm"]
RetrievalStrategy = Literal["lexical", "vector", "hybrid"]

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")
_QUESTION_SUFFIXES = (
    "在哪裡",
    "在哪",
    "哪裡",
    "是什麼",
    "是什么",
    "什麼",
    "什么",
    "嗎",
    "吗",
    "呢",
)


@dataclass(frozen=True)
class RetrievedCandidate:
    section_id: UUID
    source_id: str
    filename: str
    heading: str
    body_md: str
    score: float
    strategy: str
    debug_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult(Sequence[RetrievedCandidate]):
    decision: RetrievalDecision
    candidates: list[RetrievedCandidate]
    rejected_candidates: list[RetrievedCandidate] = field(default_factory=list)

    def __iter__(self) -> Iterator[RetrievedCandidate]:
        return iter(self.candidates)

    def __len__(self) -> int:
        return len(self.candidates)

    @overload
    def __getitem__(self, index: int) -> RetrievedCandidate: ...

    @overload
    def __getitem__(self, index: slice) -> list[RetrievedCandidate]: ...

    def __getitem__(self, index: int | slice) -> RetrievedCandidate | list[RetrievedCandidate]:
        return self.candidates[index]


def expand_query_terms(query: str, *, max_terms: int = 16) -> list[str]:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    raw_tokens = _TOKEN_RE.findall(normalized)
    candidates: list[str] = []

    for token in raw_tokens:
        stripped = _strip_question_suffix(token)
        candidates.append(stripped)
        if stripped != token:
            candidates.append(token)

        for cjk_text in _CJK_RE.findall(stripped):
            candidates.extend(_cjk_ngrams(cjk_text))
        for cjk_text in _CJK_RE.findall(token):
            candidates.extend(_cjk_ngrams(cjk_text))

    terms = _unique_terms(term for term in candidates if len(term) >= 2)
    return terms[:max_terms]


def expanded_query_text(query: str) -> str:
    terms = expand_query_terms(query)
    return " ".join(terms) if terms else query.strip()


def _strip_question_suffix(token: str) -> str:
    for suffix in _QUESTION_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix):
            return token[: -len(suffix)]
    return token


def _cjk_ngrams(text: str) -> list[str]:
    if len(text) < 2:
        return []

    ngrams: list[str] = []
    minimum_size = 2
    maximum_size = min(len(text), 6)
    for size in range(maximum_size, minimum_size - 1, -1):
        for start in range(0, len(text) - size + 1):
            ngrams.append(text[start : start + size])
    return ngrams


def _unique_terms(terms: Iterator[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        unique.append(term)
    return unique
