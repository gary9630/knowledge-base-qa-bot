from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from app.answer.citations import (
    CANNOT_CONFIRM_ANSWER,
    CitationValidationResult,
    validate_citations,
)
from app.answer.providers import AnswerProvider, AnswerSource, StreamingAnswerProvider
from app.provider_telemetry import ProviderCallContext, ProviderCallRecord


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    sources: list[AnswerSource]
    valid: bool = True
    citation_errors: list[str] = field(default_factory=list)
    cannot_confirm_reason: str | None = None
    provider_calls: list[dict[str, object]] = field(default_factory=list)


class AnswerService:
    def __init__(
        self,
        provider: AnswerProvider,
        *,
        client_request_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._provider_context = ProviderCallContext(client_request_id=client_request_id)

    def provider_call_payloads(self) -> list[dict[str, object]]:
        return [record.to_dict() for record in self._provider_context.records]

    def provider_call_records(self) -> list[ProviderCallRecord]:
        return list(self._provider_context.records)

    def answer(self, query: str, sources: Sequence[object]) -> AnswerResult:
        answer_sources = [_to_answer_source(source) for source in sources]
        if not answer_sources:
            return AnswerResult(
                answer=CANNOT_CONFIRM_ANSWER,
                sources=[],
                cannot_confirm_reason="no_sources",
            )

        first_answer = self._generate_answer(query, answer_sources, strict=False)
        first_validation = validate_citations(
            first_answer,
            (source.source_id for source in answer_sources),
        )
        if first_validation.valid:
            return self._with_provider_calls(
                _result_from_valid_answer(
                    first_answer,
                    answer_sources,
                    first_validation,
                )
            )

        retry_answer = self._generate_answer(query, answer_sources, strict=True)
        retry_validation = validate_citations(
            retry_answer,
            (source.source_id for source in answer_sources),
        )
        if retry_validation.valid:
            return self._with_provider_calls(
                _result_from_valid_answer(
                    retry_answer,
                    answer_sources,
                    retry_validation,
                )
            )

        return self._with_provider_calls(
            AnswerResult(
                answer=CANNOT_CONFIRM_ANSWER,
                sources=[],
                valid=False,
                citation_errors=_citation_errors(retry_validation),
                cannot_confirm_reason="invalid_citations",
            )
        )

    def stream_answer(self, query: str, sources: Sequence[object]) -> Iterator[str]:
        answer_sources = [_to_answer_source(source) for source in sources]
        if not answer_sources:
            yield CANNOT_CONFIRM_ANSWER
            return

        stream_with_context = getattr(self._provider, "stream_answer_with_context", None)
        if callable(stream_with_context):
            yield from stream_with_context(
                query,
                answer_sources,
                strict=False,
                context=self._provider_context,
            )
            return

        if isinstance(self._provider, StreamingAnswerProvider):
            yield from self._provider.stream_answer(
                query,
                answer_sources,
                strict=False,
            )
            return

        answer = self._generate_answer(query, answer_sources, strict=False)
        yield from _text_chunks(answer)

    def validate_generated_answer(
        self,
        answer: str,
        sources: Sequence[object],
    ) -> AnswerResult:
        answer_sources = [_to_answer_source(source) for source in sources]
        if not answer_sources:
            return AnswerResult(
                answer=CANNOT_CONFIRM_ANSWER,
                sources=[],
                cannot_confirm_reason="no_sources",
            )

        validation = validate_citations(
            answer,
            (source.source_id for source in answer_sources),
        )
        if validation.valid:
            return self._with_provider_calls(
                _result_from_valid_answer(answer, answer_sources, validation)
            )

        return self._with_provider_calls(
            AnswerResult(
                answer=CANNOT_CONFIRM_ANSWER,
                sources=[],
                valid=False,
                citation_errors=_citation_errors(validation),
                cannot_confirm_reason="invalid_citations",
            )
        )

    def _generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool,
    ) -> str:
        generate_with_context = getattr(self._provider, "generate_answer_with_context", None)
        if callable(generate_with_context):
            result = generate_with_context(
                query,
                sources,
                strict=strict,
                context=self._provider_context,
            )
            if isinstance(result, str):
                return result
            raise TypeError("generate_answer_with_context must return a string")
        return self._provider.generate_answer(query, sources, strict=strict)

    def _with_provider_calls(self, result: AnswerResult) -> AnswerResult:
        return _replace_provider_calls(result, self.provider_call_payloads())


def _result_from_valid_answer(
    answer: str,
    sources: Sequence[AnswerSource],
    validation: CitationValidationResult,
) -> AnswerResult:
    cited_sources = [
        source for source in sources if source.source_id in validation.cited_source_ids
    ]
    return AnswerResult(
        answer=answer,
        sources=cited_sources,
        cannot_confirm_reason=(
            "provider_cannot_confirm" if answer == CANNOT_CONFIRM_ANSWER else None
        ),
    )


def _to_answer_source(source: object) -> AnswerSource:
    return AnswerSource(
        source_id=_required_str_attr(source, "source_id"),
        filename=_required_str_attr(source, "filename"),
        heading=_required_str_attr(source, "heading"),
        body_md=_body_markdown(source),
        score=_optional_float_attr(source, "score"),
    )


def _body_markdown(source: object) -> str:
    body_md = getattr(source, "body_md", None)
    if isinstance(body_md, str):
        return body_md

    excerpt = getattr(source, "excerpt", None)
    if isinstance(excerpt, str):
        return excerpt

    raise TypeError("answer sources must expose a string 'body_md' or 'excerpt' attribute")


def _required_str_attr(source: object, name: str) -> str:
    value = getattr(source, name, None)
    if not isinstance(value, str):
        raise TypeError(f"answer sources must expose a string '{name}' attribute")
    return value


def _optional_float_attr(source: object, name: str) -> float | None:
    value = getattr(source, name, None)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"answer source '{name}' must be numeric when present")
    return float(value)


def _citation_errors(validation: CitationValidationResult) -> list[str]:
    errors: list[str] = []
    if validation.missing_citations:
        errors.append("answer omitted citations")
    if validation.invalid_source_ids:
        invalid_ids = ", ".join(sorted(validation.invalid_source_ids))
        errors.append(f"answer cited unselected source IDs: {invalid_ids}")
    if validation.citations_on_cannot_confirm:
        errors.append("cannot-confirm answers must not include citations")
    return errors


def _replace_provider_calls(
    result: AnswerResult,
    provider_calls: list[dict[str, object]],
) -> AnswerResult:
    return AnswerResult(
        answer=result.answer,
        sources=result.sources,
        valid=result.valid,
        citation_errors=result.citation_errors,
        cannot_confirm_reason=result.cannot_confirm_reason,
        provider_calls=provider_calls,
    )


def _text_chunks(text: str, *, chunk_size: int = 12) -> Iterator[str]:
    if not text:
        yield ""
        return

    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]
