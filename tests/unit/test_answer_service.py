from __future__ import annotations

from collections.abc import Iterator, Sequence
from uuid import UUID, uuid4

import pytest

from app.answer.citations import CANNOT_CONFIRM_ANSWER, validate_citations
from app.answer.providers import AnswerSource, FakeAnswerProvider
from app.answer.service import AnswerService
from app.provider_telemetry import ProviderCallContext, ProviderCallRecord
from app.retrieval.models import RetrievedCandidate


def test_validate_citations_rejects_missing_and_unallowed_source_id() -> None:
    allowed_source_ids = {"常見問題FAQ.md#課程網站"}

    missing = validate_citations("課程網站位於學習平台。", allowed_source_ids)
    unallowed = validate_citations(
        "課程網站位於學習平台。 [missing.md#課程網站]",
        allowed_source_ids,
    )

    assert not missing.valid
    assert missing.missing_citations
    assert missing.cited_source_ids == set()
    assert not unallowed.valid
    assert unallowed.invalid_source_ids == {"missing.md#課程網站"}


def test_validate_citations_accepts_cjk_source_id_with_surrounding_punctuation() -> None:
    allowed_source_ids = {"docs/常見問題FAQ.md#課程網站"}

    result = validate_citations(
        "課程網站位於學習平台首頁（docs/常見問題FAQ.md#課程網站）。",
        allowed_source_ids,
    )

    assert result.valid
    assert result.cited_source_ids == allowed_source_ids
    assert result.invalid_source_ids == set()


def test_validate_citations_accepts_anchor_with_heading_punctuation() -> None:
    allowed_source_ids = {"3-常用技術-01-Database.md#為什麼資料庫的選擇這麼複雜"}

    result = validate_citations(
        "資料庫選型牽涉多種取捨。 [3-常用技術-01-Database.md#為什麼資料庫的選擇這麼複雜？]",
        allowed_source_ids,
    )

    assert result.valid
    assert result.cited_source_ids == allowed_source_ids
    assert result.invalid_source_ids == set()


def test_validate_citations_accepts_anchor_with_spaces_and_case_variants() -> None:
    allowed_source_ids = {"faq.md#course-site"}

    result = validate_citations(
        "課程網站在學習平台。 [faq.md#Course Site]",
        allowed_source_ids,
    )

    assert result.valid
    assert result.cited_source_ids == allowed_source_ids
    assert result.invalid_source_ids == set()


def test_validate_citations_does_not_treat_markdown_url_anchor_as_source_id() -> None:
    result = validate_citations(
        "更多背景可參考 https://example.md#anchor",
        {"faq.md#course-site"},
    )

    assert not result.valid
    assert result.missing_citations
    assert result.invalid_source_ids == set()


def test_validate_citations_accepts_bracketed_source_id_with_spaces_in_filename() -> None:
    allowed_source_ids = {"release notes.md#課程網站"}

    result = validate_citations(
        "課程網站位於學習平台首頁。 [release notes.md#課程網站]",
        allowed_source_ids,
    )

    assert result.valid
    assert result.cited_source_ids == allowed_source_ids
    assert result.invalid_source_ids == set()


def test_validate_citations_accepts_bare_source_id_token() -> None:
    result = validate_citations(
        "faq.md#intro",
        {"faq.md#intro"},
    )

    assert result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == set()


def test_validate_citations_rejects_unallowed_bracketed_source_id_with_punctuation() -> None:
    result = validate_citations(
        "課程網站在首頁。 [faq.md#intro] 但不是草稿內容。 [release (draft).md#intro]",
        {"faq.md#intro"},
    )

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == {"release (draft).md#intro"}


def test_validate_citations_ignores_markdown_link_url_anchor_with_valid_citation() -> None:
    result = validate_citations(
        "安裝步驟見知識庫。 [faq.md#intro] 可另參考 [docs](https://example.com/guide.md#install)。",
        {"faq.md#intro"},
    )

    assert result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == set()


def test_validate_citations_ignores_markdown_link_url_anchor_before_valid_citation() -> None:
    result = validate_citations(
        "[docs](https://example.com/guide.md#install) [faq.md#intro]",
        {"faq.md#intro"},
    )

    assert result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == set()


def test_validate_citations_rejects_relative_markdown_link_target_source_id() -> None:
    result = validate_citations(
        "Valid [faq.md#intro] see [draft](release.md#intro)",
        {"faq.md#intro"},
    )

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == {"release.md#intro"}


def test_validate_citations_rejects_bracketed_source_id_with_closing_bracket_in_filename() -> None:
    result = validate_citations(
        "Valid [faq.md#intro] invalid [release [draft].md#intro]",
        {"faq.md#intro"},
    )

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == {"release [draft].md#intro"}


def test_validate_citations_rejects_raw_source_id_with_parentheses_in_filename() -> None:
    result = validate_citations(
        "Valid [faq.md#intro] invalid release (draft).md#intro",
        {"faq.md#intro"},
    )

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == {"release (draft).md#intro"}


def test_validate_citations_rejects_raw_source_id_with_no_space_parentheses_in_filename() -> None:
    result = validate_citations(
        "Valid [faq.md#intro] invalid release(draft).md#intro",
        {"faq.md#intro"},
    )

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == {"release(draft).md#intro"}


def test_validate_citations_rejects_raw_source_id_with_brackets_in_filename() -> None:
    result = validate_citations(
        "Valid [faq.md#intro] invalid release [draft].md#intro",
        {"faq.md#intro"},
    )

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == {"release [draft].md#intro"}


def test_validate_citations_rejects_raw_source_id_with_no_space_brackets_in_filename() -> None:
    result = validate_citations(
        "Valid [faq.md#intro] invalid release[draft].md#intro",
        {"faq.md#intro"},
    )

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == {"release[draft].md#intro"}


@pytest.mark.parametrize(
    ("answer", "invalid_source_id"),
    [
        ('Valid [faq.md#intro] invalid "missing.md#secret"', "missing.md#secret"),
        ("Valid [faq.md#intro] invalid 'missing.md#secret'", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid `missing.md#secret`", "missing.md#secret"),
        ('Valid [faq.md#intro] invalid "release notes.md#secret"', "release notes.md#secret"),
    ],
)
def test_validate_citations_rejects_quoted_raw_source_id_bypass(
    answer: str,
    invalid_source_id: str,
) -> None:
    result = validate_citations(answer, {"faq.md#intro"})

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert result.invalid_source_ids == {invalid_source_id}


@pytest.mark.parametrize(
    ("answer", "invalid_source_id"),
    [
        ('Valid [faq.md#intro] invalid missing.md#secret"', "missing.md#secret"),
        ("Valid [faq.md#intro] invalid missing.md#secret'", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid missing.md#secret`", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid “missing.md#secret”", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid ‘missing.md#secret’", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid missing.md#secret”", "missing.md#secret"),
    ],
)
def test_validate_citations_rejects_quote_boundary_raw_source_id_bypass(
    answer: str,
    invalid_source_id: str,
) -> None:
    result = validate_citations(answer, {"faq.md#intro"})

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert any(invalid_source_id in source_id for source_id in result.invalid_source_ids)


@pytest.mark.parametrize(
    ("answer", "invalid_source_id"),
    [
        ("Valid [faq.md#intro] invalid 「missing.md#secret」", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid 『missing.md#secret』", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid 《missing.md#secret》", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid 〈missing.md#secret〉", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid missing.md#secret）", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid missing.md#secret】", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid missing.md#secret…", "missing.md#secret"),
        ("Valid [faq.md#intro] invalid missing.md#secret—extra", "missing.md#secret"),
    ],
)
def test_validate_citations_rejects_cjk_delimited_raw_source_id_bypass(
    answer: str,
    invalid_source_id: str,
) -> None:
    result = validate_citations(answer, {"faq.md#intro"})

    assert not result.valid
    assert result.cited_source_ids == {"faq.md#intro"}
    assert any(invalid_source_id in source_id for source_id in result.invalid_source_ids)


@pytest.mark.parametrize(
    ("answer", "invalid_source_id"),
    [
        ("Valid release,faq.md#intro", "release,faq.md#intro"),
        ("Valid release:faq.md#intro", "release:faq.md#intro"),
        ("Valid release faq.md#intro", "release faq.md#intro"),
        ("Valid release&faq.md#intro", "release&faq.md#intro"),
        ("Valid release;faq.md#intro", "release;faq.md#intro"),
        ("Valid release!faq.md#intro", "release!faq.md#intro"),
        ("Valid release]faq.md#intro", "release]faq.md#intro"),
        ("Valid release，faq.md#intro", "release，faq.md#intro"),
        ("Valid release; faq.md#intro", "release; faq.md#intro"),
        ("Valid release! faq.md#intro", "release! faq.md#intro"),
        ("Valid release， faq.md#intro", "release， faq.md#intro"),
        ("Valid release: faq.md#intro", "release: faq.md#intro"),
        ("Valid release, faq.md#intro", "release, faq.md#intro"),
        ("Valid release, faq.md#intro.", "release, faq.md#intro"),
        ("Valid release; faq.md#intro.", "release; faq.md#intro"),
        ("Valid release(draft).md#intro.", "release(draft).md#intro"),
    ],
)
def test_validate_citations_rejects_raw_source_id_suffix_bypass(
    answer: str,
    invalid_source_id: str,
) -> None:
    result = validate_citations(answer, {"faq.md#intro"})

    assert not result.valid
    assert result.cited_source_ids == set()
    assert result.invalid_source_ids == {invalid_source_id}


def test_answer_without_sources_returns_cannot_confirm_without_provider_call() -> None:
    provider = FakeAnswerProvider(["課程網站位於學習平台。 [faq.md#course-site]"])
    service = AnswerService(provider)

    result = service.answer("課程網站在哪裡？", [])

    assert result.answer == CANNOT_CONFIRM_ANSWER
    assert result.sources == []
    assert result.valid
    assert result.citation_errors == []
    assert result.cannot_confirm_reason == "no_sources"
    assert provider.calls == []


def test_answer_with_valid_fake_provider_answer_returns_selected_sources() -> None:
    source = _candidate(
        source_id="常見問題FAQ.md#課程網站",
        filename="常見問題FAQ.md",
        heading="課程網站",
        body_md="## 課程網站\n\n課程網站位於學習平台首頁。",
    )
    provider = FakeAnswerProvider(["課程網站位於學習平台首頁。 [常見問題FAQ.md#課程網站]"])
    service = AnswerService(provider)

    result = service.answer("課程網站在哪裡？", [source])

    assert result.answer == "課程網站位於學習平台首頁。 [常見問題FAQ.md#課程網站]"
    assert result.valid
    assert result.citation_errors == []
    assert result.cannot_confirm_reason is None
    assert [answer_source.source_id for answer_source in result.sources] == [source.source_id]
    assert [call.strict for call in provider.calls] == [False]


def test_answer_retries_once_after_invalid_citation_and_returns_retry_answer() -> None:
    source = _candidate(source_id="faq.md#course-site")
    provider = FakeAnswerProvider(
        [
            "課程網站在平台首頁。 [other.md#course-site]",
            "課程網站在平台首頁。 [faq.md#course-site]",
        ]
    )
    service = AnswerService(provider)

    result = service.answer("課程網站在哪裡？", [source])

    assert result.answer == "課程網站在平台首頁。 [faq.md#course-site]"
    assert result.valid
    assert result.citation_errors == []
    assert result.cannot_confirm_reason is None
    assert [call.strict for call in provider.calls] == [False, True]


def test_answer_falls_back_when_retry_still_has_invalid_citation() -> None:
    source = _candidate(source_id="faq.md#course-site")
    provider = FakeAnswerProvider(
        [
            "課程網站在平台首頁。 [other.md#course-site]",
            "課程網站在平台首頁。 [missing.md#course-site]",
        ]
    )
    service = AnswerService(provider)

    result = service.answer("課程網站在哪裡？", [source])

    assert result.answer == CANNOT_CONFIRM_ANSWER
    assert result.sources == []
    assert not result.valid
    assert result.citation_errors
    assert result.cannot_confirm_reason == "invalid_citations"
    assert [call.strict for call in provider.calls] == [False, True]


def test_answer_keeps_partially_grounded_retry_answer_with_warnings() -> None:
    source = _candidate(source_id="faq.md#course-site")
    provider = FakeAnswerProvider(
        [
            "課程網站在平台首頁。 [missing.md#course-site]",
            "課程網站在平台首頁。 [faq.md#course-site] 另見 [missing.md#course-site]",
        ]
    )
    service = AnswerService(provider)

    result = service.answer("課程網站在哪裡？", [source])

    expected_answer = "課程網站在平台首頁。 [faq.md#course-site] 另見 [missing.md#course-site]"
    assert result.answer == expected_answer
    assert result.valid
    assert [answer_source.source_id for answer_source in result.sources] == [source.source_id]
    assert result.citation_errors == [
        "answer cited unselected source IDs: missing.md#course-site"
    ]
    assert result.cannot_confirm_reason is None
    assert [call.strict for call in provider.calls] == [False, True]


def test_cannot_confirm_answer_with_no_citations_is_valid_with_sources_available() -> None:
    source = _candidate(source_id="faq.md#course-site")
    provider = FakeAnswerProvider([CANNOT_CONFIRM_ANSWER])
    service = AnswerService(provider)

    result = service.answer("這個產品支援火星部署嗎？", [source])

    assert result.answer == CANNOT_CONFIRM_ANSWER
    assert result.sources == []
    assert result.valid
    assert result.citation_errors == []
    assert result.cannot_confirm_reason == "provider_cannot_confirm"
    assert [call.strict for call in provider.calls] == [False]


def test_stream_answer_uses_provider_deltas_and_validates_final_answer() -> None:
    source = _candidate(source_id="faq.md#course-site")
    provider = StreamingAnswerProvider(["Course ", "site. [faq.md#course-site]"])
    service = AnswerService(provider, client_request_id="request-123")

    tokens = list(service.stream_answer("Where is the course site?", [source]))
    result = service.validate_generated_answer("".join(tokens), [source])

    assert tokens == ["Course ", "site. [faq.md#course-site]"]
    assert result.answer == "Course site. [faq.md#course-site]"
    assert result.valid
    assert [answer_source.source_id for answer_source in result.sources] == [source.source_id]
    assert provider.stream_calls == [
        (False, ("faq.md#course-site",), "request-123")
    ]
    assert service.provider_call_payloads()[0]["client_request_id"] == "request-123-1"


def test_validate_generated_stream_answer_downgrades_invalid_citations() -> None:
    source = _candidate(source_id="faq.md#course-site")
    service = AnswerService(FakeAnswerProvider())

    result = service.validate_generated_answer(
        "Course site. [missing.md#course-site]",
        [source],
    )

    assert result.answer == CANNOT_CONFIRM_ANSWER
    assert result.sources == []
    assert not result.valid
    assert result.cannot_confirm_reason == "invalid_citations"
    assert result.citation_errors == [
        "answer cited unselected source IDs: missing.md#course-site"
    ]


def test_validate_generated_stream_answer_keeps_partially_grounded_answer() -> None:
    source = _candidate(source_id="faq.md#course-site")
    service = AnswerService(FakeAnswerProvider())

    result = service.validate_generated_answer(
        "Course site. [faq.md#course-site] See also [missing.md#course-site]",
        [source],
    )

    assert result.answer == "Course site. [faq.md#course-site] See also [missing.md#course-site]"
    assert result.valid
    assert [answer_source.source_id for answer_source in result.sources] == [source.source_id]
    assert result.citation_errors == [
        "answer cited unselected source IDs: missing.md#course-site"
    ]
    assert result.cannot_confirm_reason is None


def _candidate(
    *,
    source_id: str,
    section_id: UUID | None = None,
    filename: str = "faq.md",
    heading: str = "Course Site",
    body_md: str = "## Course Site\n\nThe course site is on the platform homepage.",
    score: float = 0.82,
    strategy: str = "hybrid",
) -> RetrievedCandidate:
    return RetrievedCandidate(
        section_id=section_id or uuid4(),
        source_id=source_id,
        filename=filename,
        heading=heading,
        body_md=body_md,
        score=score,
        strategy=strategy,
    )


class StreamingAnswerProvider:
    def __init__(self, tokens: Sequence[str]) -> None:
        self._tokens = list(tokens)
        self.stream_calls: list[tuple[bool, tuple[str, ...], str | None]] = []

    def generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> str:
        raise AssertionError("streaming path should not call generate_answer")

    def stream_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> Iterator[str]:
        self.stream_calls.append((strict, tuple(source.source_id for source in sources), None))
        yield from self._tokens

    def stream_answer_with_context(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
        context: ProviderCallContext,
    ) -> Iterator[str]:
        self.stream_calls.append(
            (strict, tuple(source.source_id for source in sources), context.client_request_id)
        )
        context.record(
            ProviderCallRecord(
                provider="openai",
                operation="chat.completions.stream",
                model="gpt-test",
                status="succeeded",
                client_request_id=context.next_client_request_id(),
                usage_complete=False,
            )
        )
        yield from self._tokens
