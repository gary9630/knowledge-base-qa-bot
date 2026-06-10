from __future__ import annotations

import json

from scripts.generate_eval_cases import (
    SectionRecord,
    build_generation_prompt,
    build_negative_prompt,
    build_verification_prompt,
    generate_eval_seed_dicts,
    group_sections,
    parse_generated_cases,
    parse_negative_cases,
    verification_passed,
)


def _records(count: int, filename: str = "doc.md") -> list[SectionRecord]:
    return [
        SectionRecord(
            filename=filename,
            source_id=f"{filename}#sec-{index}",
            heading=f"Heading {index}",
            body_md=f"Body text {index}",
        )
        for index in range(count)
    ]


def test_group_sections_builds_consecutive_groups_per_file() -> None:
    records = _records(5)
    groups = group_sections(records, group_size=3)

    assert all(group.filename == "doc.md" for group in groups)
    assert [len(group.sections) for group in groups] == [3, 2]
    assert groups[0].sections[0].source_id == "doc.md#sec-0"
    assert groups[1].sections[0].source_id == "doc.md#sec-3"


def test_group_sections_does_not_mix_files() -> None:
    records = _records(2, filename="a.md") + _records(2, filename="b.md")
    groups = group_sections(records, group_size=3)

    filenames = {group.filename for group in groups}
    assert filenames == {"a.md", "b.md"}
    for group in groups:
        assert all(section.filename == group.filename for section in group.sections)


def test_parse_generated_cases_keeps_only_allowed_source_ids() -> None:
    raw = json.dumps(
        {
            "cases": [
                {
                    "name": "valid case",
                    "query": "課程網站在哪裡？",
                    "expected_source_ids": ["doc.md#sec-1"],
                },
                {
                    "name": "hallucinated source",
                    "query": "亂掰的問題",
                    "expected_source_ids": ["other.md#nope"],
                },
                {"name": "missing query"},
            ]
        }
    )

    cases = parse_generated_cases(raw, allowed_source_ids={"doc.md#sec-1"})

    assert len(cases) == 1
    assert cases[0]["query"] == "課程網站在哪裡？"
    assert cases[0]["expected_source_ids"] == ["doc.md#sec-1"]


def test_parse_generated_cases_rejects_invalid_json() -> None:
    assert parse_generated_cases("not json", allowed_source_ids=set()) == []


def test_parse_negative_cases_returns_queries_only() -> None:
    raw = json.dumps({"cases": [{"name": "neg", "query": "本課程有期末考嗎？"}]})

    cases = parse_negative_cases(raw)

    assert cases == [{"name": "neg", "query": "本課程有期末考嗎？"}]


def test_verification_passed_parses_answerable_flag() -> None:
    assert verification_passed(json.dumps({"answerable": True})) is True
    assert verification_passed(json.dumps({"answerable": False})) is False
    assert verification_passed("garbage") is False


def test_prompts_contain_sections_and_query() -> None:
    records = _records(2)
    group = group_sections(records, group_size=2)[0]

    generation = build_generation_prompt(group, case_count=2)
    assert "doc.md#sec-0" in generation
    assert "Body text 1" in generation

    negative = build_negative_prompt([group], case_count=2)
    assert "doc.md" in negative

    verification = build_verification_prompt(
        query="課程網站在哪裡？",
        sections=list(group.sections),
    )
    assert "課程網站在哪裡？" in verification
    assert "doc.md#sec-0" in verification


class FakeCaller:
    """Returns canned generation, then verification responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._responses.pop(0)


def test_generate_eval_seed_dicts_verifies_and_namespaces_cases() -> None:
    records = _records(3)
    groups = group_sections(records, group_size=3)
    generation_response = json.dumps(
        {
            "cases": [
                {
                    "name": "fact",
                    "query": "Heading 0 是什麼？",
                    "expected_source_ids": ["doc.md#sec-0"],
                },
                {
                    "name": "cross-section",
                    "query": "綜合問題？",
                    "expected_source_ids": ["doc.md#sec-0", "doc.md#sec-1"],
                },
            ]
        }
    )
    verification_ok = json.dumps({"answerable": True})
    verification_bad = json.dumps({"answerable": False})
    negative_response = json.dumps({"cases": [{"name": "neg", "query": "有期末考嗎？"}]})
    caller = FakeCaller(
        [generation_response, verification_ok, verification_bad, negative_response]
    )

    seed_dicts = generate_eval_seed_dicts(
        caller,
        groups,
        target_count=2,
        negative_count=1,
        max_rounds=1,
    )

    positive = [case for case in seed_dicts if case["expected_decision"] == "can_answer"]
    negative = [case for case in seed_dicts if case["expected_decision"] == "cannot_confirm"]
    assert len(positive) == 1  # second case failed verification
    assert len(negative) == 1
    assert positive[0]["seed_key"].startswith("auto.")
    assert positive[0]["tags"] == ["auto"]
    assert negative[0]["expected_source_ids"] == []
    seed_keys = [case["seed_key"] for case in seed_dicts]
    assert len(seed_keys) == len(set(seed_keys))
