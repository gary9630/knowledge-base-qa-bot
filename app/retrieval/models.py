from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, overload
from uuid import UUID

RetrievalDecision = Literal["can_answer", "cannot_confirm"]
RetrievalStrategy = Literal["lexical", "markdown", "vector", "hybrid"]
SOURCE_TYPE_PRIORITIES = {
    "course_policy": 5,
    "policy": 5,
    "announcement": 4,
    "official_handout": 3,
    "handout": 3,
    "session_summary": 2,
    "summary": 2,
    "transcript": 1,
    "qa": 0,
    "q&a": 0,
    "imported": 0,
    "markdown": 0,
}

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
    source_type: str = "unknown"
    source_priority: int = 0
    debug_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalDiagnostics:
    strategy: str
    requested_limit: int
    score_threshold: float
    raw_candidate_count: int = 0
    merged_candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    top_score: float | None = None
    selected_source_ids: tuple[str, ...] = ()
    rejected_source_ids: tuple[str, ...] = ()
    strategy_counts: dict[str, int] = field(default_factory=dict)
    score_debug_by_source_id: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult(Sequence[RetrievedCandidate]):
    decision: RetrievalDecision
    candidates: list[RetrievedCandidate]
    rejected_candidates: list[RetrievedCandidate] = field(default_factory=list)
    diagnostics: RetrievalDiagnostics = field(
        default_factory=lambda: RetrievalDiagnostics(
            strategy="hybrid",
            requested_limit=0,
            score_threshold=0.0,
        )
    )

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


def source_priority_for(source_type: str, metadata: dict[str, object] | None = None) -> int:
    metadata_priority = (metadata or {}).get("source_priority")
    parsed_priority = _parse_source_priority(metadata_priority)
    if parsed_priority is not None:
        return parsed_priority
    return SOURCE_TYPE_PRIORITIES.get(source_type.casefold(), 0)


def _parse_source_priority(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return _normalize_priority(value)
    if isinstance(value, float):
        return _normalize_priority(round(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return _normalize_priority(round(float(stripped)))
        except ValueError:
            return SOURCE_TYPE_PRIORITIES.get(stripped.casefold())
    return None


def _normalize_priority(value: int) -> int:
    if value > 10:
        value = round(value / 10)
    return min(5, max(0, value))


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
