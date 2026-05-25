from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

CANNOT_CONFIRM_ANSWER = "我無法從知識庫確認這件事。"

_SOURCE_ID_TOKEN_RE = re.compile(
    r"(?<![\w./%+-])(?P<source_id>[\w%+@=-][\w./%+@=-]*\.md#[\w-]+)(?![\w/%+-])",
    re.UNICODE,
)
_RAW_PUNCTUATED_SOURCE_ID_RE = re.compile(
    r"(?<![\w./%+-])"
    r"(?P<source_id>[\w./%+@=-]+ [\(\[（【][^\r\n]+?[\)\]）】][\w./%+@=-]*\.md#[\w-]+)"
    r"(?![\w/%+-])",
    re.UNICODE,
)
_BRACKETED_SOURCE_ID_CONTENT_RE = re.compile(r"^(?P<source_id>.+\.md#[\w-]+)$", re.UNICODE)
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_URL_SOURCE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S*?\.md#[\w-]+", re.UNICODE)
_BRACKET_PAIRS = {
    "[": "]",
    "(": ")",
    "（": "）",
    "【": "】",
}


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
    bracketed_matches, bracketed_spans = _extract_bracketed_source_ids(answer)
    answer_without_bracketed_citations = _mask_spans(answer, bracketed_spans)
    answer_without_urls = _mask_spans(
        answer_without_bracketed_citations,
        _url_source_id_spans(answer_without_bracketed_citations),
    )
    token_matches = {
        match.group("source_id").strip()
        for match in _SOURCE_ID_TOKEN_RE.finditer(answer_without_urls)
    }
    punctuated_matches = {
        match.group("source_id").strip()
        for match in _RAW_PUNCTUATED_SOURCE_ID_RE.finditer(answer_without_urls)
    }
    return token_matches | punctuated_matches | bracketed_matches


def _extract_bracketed_source_ids(answer: str) -> tuple[set[str], list[tuple[int, int]]]:
    source_ids: set[str] = set()
    spans_to_mask: list[tuple[int, int]] = []
    index = 0

    while index < len(answer):
        opener = answer[index]
        closer = _BRACKET_PAIRS.get(opener)
        if closer is None:
            index += 1
            continue

        candidate = _bracket_content_candidate(answer, index, closer)
        if candidate is None:
            index += 1
            continue

        source_id, is_url, span = candidate
        if is_url:
            spans_to_mask.append(span)
            index = span[1]
            continue

        if source_id is not None:
            source_ids.add(source_id)
            spans_to_mask.append(span)
            index = span[1]
            continue

        index += 1

    return source_ids, spans_to_mask


def _bracket_content_candidate(
    answer: str,
    start: int,
    closer: str,
) -> tuple[str | None, bool, tuple[int, int]] | None:
    search_start = start + 1
    while search_start < len(answer):
        end = answer.find(closer, search_start)
        if end == -1:
            return None

        content = answer[start + 1 : end].strip()
        is_url = _looks_like_url(content)
        source_id = None if is_url else _source_id_from_bracket_content(content)
        if is_url or source_id is not None:
            return source_id, is_url, (start, end + 1)

        search_start = end + 1

    return None


def _source_id_from_bracket_content(content: str) -> str | None:
    if not content or "\n" in content or "\r" in content:
        return None

    match = _BRACKETED_SOURCE_ID_CONTENT_RE.match(content)
    if match is None:
        return None

    return match.group("source_id")


def _looks_like_url(content: str) -> bool:
    return bool(_URL_RE.match(content))


def _url_source_id_spans(answer: str) -> list[tuple[int, int]]:
    return [match.span() for match in _URL_SOURCE_ID_RE.finditer(answer)]


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
