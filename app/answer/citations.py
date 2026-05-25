from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

CANNOT_CONFIRM_ANSWER = "我無法從知識庫確認這件事。"

_SOURCE_ID_TOKEN_RE = re.compile(
    r"(?<![\w./%+-])(?P<source_id>[\w%+@=-][\w./%+@=-]*\.md#[\w-]+)(?![\w/%+-])",
    re.UNICODE,
)
_BRACKETED_SOURCE_ID_RE = re.compile(
    r"[\[\(（【](?P<source_id>[^\]\)）】\n\r]+?\.md#[\w-]+)[\]\)）】]",
    re.UNICODE,
)


@dataclass(frozen=True)
class CitationValidationResult:
    valid: bool
    cited_source_ids: set[str]
    invalid_source_ids: set[str]
    missing_citations: bool
    citations_on_cannot_confirm: bool = False


def validate_citations(
    answer: str,
    allowed_source_ids: Iterable[str],
) -> CitationValidationResult:
    allowed = {source_id for source_id in allowed_source_ids if source_id}
    cited_source_ids = _extract_cited_source_ids(answer, allowed)
    invalid_source_ids = _extract_source_id_tokens(answer) - allowed
    has_any_citation = bool(cited_source_ids or invalid_source_ids)
    is_cannot_confirm = answer.strip() == CANNOT_CONFIRM_ANSWER
    mentions_cannot_confirm = CANNOT_CONFIRM_ANSWER in answer

    missing_citations = bool(allowed) and not has_any_citation and not is_cannot_confirm
    citations_on_cannot_confirm = mentions_cannot_confirm and has_any_citation
    valid = not invalid_source_ids and not missing_citations and not citations_on_cannot_confirm

    return CitationValidationResult(
        valid=valid,
        cited_source_ids=cited_source_ids,
        invalid_source_ids=invalid_source_ids,
        missing_citations=missing_citations,
        citations_on_cannot_confirm=citations_on_cannot_confirm,
    )


def _extract_cited_source_ids(answer: str, allowed_source_ids: set[str]) -> set[str]:
    detected_tokens = _extract_source_id_tokens(answer)
    cited_source_ids = detected_tokens & allowed_source_ids

    for source_id in allowed_source_ids:
        if _contains_source_id(answer, source_id):
            cited_source_ids.add(source_id)

    return cited_source_ids


def _extract_source_id_tokens(answer: str) -> set[str]:
    bracketed_spans: list[tuple[int, int]] = []
    bracketed_matches: set[str] = set()
    for match in _BRACKETED_SOURCE_ID_RE.finditer(answer):
        bracketed_matches.add(match.group("source_id").strip())
        bracketed_spans.append(match.span())

    answer_without_bracketed_citations = _mask_spans(answer, bracketed_spans)
    token_matches = {
        match.group("source_id").strip()
        for match in _SOURCE_ID_TOKEN_RE.finditer(answer_without_bracketed_citations)
    }
    return token_matches | bracketed_matches


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text

    characters = list(text)
    for start, end in spans:
        for index in range(start, end):
            characters[index] = " "
    return "".join(characters)


def _contains_source_id(answer: str, source_id: str) -> bool:
    for match in re.finditer(re.escape(source_id), answer):
        before = answer[match.start() - 1] if match.start() > 0 else ""
        after = answer[match.end()] if match.end() < len(answer) else ""
        if not _is_source_id_character(before) and not _is_source_id_character(after):
            return True
    return False


def _is_source_id_character(character: str) -> bool:
    return bool(character) and (character.isalnum() or character in "._/#%+-=@")
