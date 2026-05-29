import pytest

from app.evals.cases import EvalSeedCase, parse_seed_cases


def test_parse_seed_cases_trims_and_deduplicates_sources() -> None:
    cases = parse_seed_cases(
        [
            {
                "seed_key": " faq.course-site ",
                "name": " FAQ course site ",
                "query": " 課程網站在哪？ ",
                "expected_decision": "can_answer",
                "expected_source_ids": [
                    " 常見問題FAQ.md#課程網站 ",
                    "常見問題FAQ.md#課程網站",
                    "",
                ],
                "tags": [" seed ", "faq", "seed"],
                "metadata": {"fixture": "default"},
            }
        ]
    )

    assert cases == [
        EvalSeedCase(
            seed_key="faq.course-site",
            name="FAQ course site",
            query="課程網站在哪？",
            expected_decision="can_answer",
            expected_source_ids=("常見問題FAQ.md#課程網站",),
            tags=("seed", "faq"),
            metadata={"fixture": "default"},
            active=True,
        )
    ]


def test_parse_seed_cases_rejects_duplicate_seed_keys() -> None:
    with pytest.raises(ValueError, match="duplicate seed_key"):
        parse_seed_cases(
            [
                {
                    "seed_key": "faq.course-site",
                    "name": "FAQ course site",
                    "query": "課程網站在哪？",
                    "expected_decision": "can_answer",
                },
                {
                    "seed_key": "faq.course-site",
                    "name": "FAQ course site duplicate",
                    "query": "課程網站在哪？",
                    "expected_decision": "can_answer",
                },
            ]
        )
