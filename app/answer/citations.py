from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

CANNOT_CONFIRM_ANSWER = "我無法從知識庫確認這件事。"

_RAW_SOURCE_ID_TOKEN_RE = re.compile(
    r"(?<!\S)(?P<source_id>\S+\.md#[\w-]+)(?!\S)",
    re.UNICODE,
)
_RAW_SPACED_SOURCE_ID_RE = re.compile(
    r"(?<!\S)(?P<source_id>[\w./%+@=-]+ +[\w./%+@=-]+\.md#[\w-]+)(?!\S)",
    re.UNICODE,
)
_RAW_PREFIX_PUNCTUATION_SOURCE_ID_RE = re.compile(
    r"(?<!\S)(?P<source_id>\S*[^\w\s] +\S+\.md#[\w-]+)(?!\S)",
    re.UNICODE,
)
_RAW_PUNCTUATED_SOURCE_ID_RE = re.compile(
    r"(?<!\S)"
    r"(?P<source_id>[\w./%+@=-]+ ?[\(\[（【][^\r\n]+?[\)\]）】][\w./%+@=-]*\.md#[\w-]+)"
    r"(?!\S)",
    re.UNICODE,
)
_BRACKETED_SOURCE_ID_CONTENT_RE = re.compile(r"^(?P<source_id>.+\.md#[\w-]+)$", re.UNICODE)
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_URL_SOURCE_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S*?\.md#[\w-]+", re.UNICODE)
_MARKDOWN_URL_LINK_RE = re.compile(
    r"\[[^\]\r\n]*\]\([A-Za-z][A-Za-z0-9+.-]*://[^\s)]*\)",
    re.UNICODE,
)
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
    return _extract_source_id_tokens(answer) & allowed_source_ids


def _extract_source_id_tokens(answer: str) -> set[str]:
    answer_without_markdown_url_links = _mask_spans(answer, _markdown_url_link_spans(answer))
    bracketed_matches, bracketed_spans = _extract_bracketed_source_ids(
        answer_without_markdown_url_links,
    )
    answer_without_bracketed_citations = _mask_spans(answer, bracketed_spans)
    answer_without_urls = _mask_spans(
        answer_without_bracketed_citations,
        _url_source_id_spans(answer_without_bracketed_citations),
    )
    spaced_match_spans = list(_RAW_SPACED_SOURCE_ID_RE.finditer(answer_without_urls))
    spaced_matches = {match.group("source_id").strip() for match in spaced_match_spans}
    prefix_punctuation_match_spans = list(
        _RAW_PREFIX_PUNCTUATION_SOURCE_ID_RE.finditer(answer_without_urls)
    )
    prefix_punctuation_matches = {
        match.group("source_id").strip() for match in prefix_punctuation_match_spans
    }
    punctuated_match_spans = list(_RAW_PUNCTUATED_SOURCE_ID_RE.finditer(answer_without_urls))
    punctuated_matches = {
        match.group("source_id").strip() for match in punctuated_match_spans
    }
    answer_without_nonstandard_raw_citations = _mask_spans(
        answer_without_urls,
        [
            match.span()
            for match in (
                spaced_match_spans
                + prefix_punctuation_match_spans
                + punctuated_match_spans
            )
        ],
    )
    token_matches = {
        match.group("source_id").strip()
        for match in _RAW_SOURCE_ID_TOKEN_RE.finditer(answer_without_nonstandard_raw_citations)
    }
    return (
        token_matches
        | spaced_matches
        | prefix_punctuation_matches
        | punctuated_matches
        | bracketed_matches
    )


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


def _markdown_url_link_spans(answer: str) -> list[tuple[int, int]]:
    return [match.span() for match in _MARKDOWN_URL_LINK_RE.finditer(answer)]


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text

    characters = list(text)
    for start, end in spans:
        for index in range(start, end):
            characters[index] = " "
    return "".join(characters)
