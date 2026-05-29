from __future__ import annotations

import json
from pathlib import Path

from scripts.real_content_acceptance import (
    AcceptanceCandidate,
    AcceptanceCase,
    evaluate_case,
    load_acceptance_cases,
    main,
    run_acceptance_cases,
)


def test_evaluate_case_passes_when_expected_filename_is_retrieved() -> None:
    case = AcceptanceCase(
        case_id="cap-theorem",
        query="CAP theorem 是什麼？",
        expected_sources=("1-基本觀念-03-CAP Theorem.md",),
        strategy="hybrid",
        limit=5,
    )

    result = evaluate_case(
        case,
        [
            AcceptanceCandidate(
                source_id="1-基本觀念-03-CAP Theorem.md#cap-theorem",
                filename="1-基本觀念-03-CAP Theorem.md",
                heading="CAP Theorem",
                score=0.92,
                strategy="hybrid",
            )
        ],
    )

    assert result.status == "passed"
    assert result.matched_sources == ("1-基本觀念-03-CAP Theorem.md",)


def test_run_acceptance_cases_reports_failed_cases_and_retrieved_sources() -> None:
    cases = (
        AcceptanceCase(
            case_id="cap-theorem",
            query="CAP theorem 是什麼？",
            expected_sources=("1-基本觀念-03-CAP Theorem.md",),
        ),
        AcceptanceCase(
            case_id="message-queue",
            query="Message Queue 適合用在哪些情境？",
            expected_sources=("3-常用技術-07-Message Queue.md",),
        ),
    )

    def search(case: AcceptanceCase) -> list[AcceptanceCandidate]:
        if case.case_id == "cap-theorem":
            return [
                AcceptanceCandidate(
                    source_id="1-基本觀念-03-CAP Theorem.md#cap",
                    filename="1-基本觀念-03-CAP Theorem.md",
                    heading="CAP",
                    score=0.8,
                    strategy="hybrid",
                )
            ]
        return [
            AcceptanceCandidate(
                source_id="2-設計模式-01-Scaling Reads.md#intro",
                filename="2-設計模式-01-Scaling Reads.md",
                heading="Scaling Reads",
                score=0.7,
                strategy="hybrid",
            )
        ]

    report = run_acceptance_cases(cases, search=search)

    assert report.status == "failed"
    assert report.summary == {"total": 2, "passed": 1, "failed": 1}
    assert report.cases[0].status == "passed"
    assert report.cases[1].status == "failed"
    assert report.cases[1].retrieved_sources == ("2-設計模式-01-Scaling Reads.md#intro",)


def test_load_acceptance_cases_reads_json_file(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    "id": "rag",
                    "query": "RAG 的流程是什麼？",
                    "expected_sources": [
                        "2-設計模式-08-RAG (Retrieval-Augmented Generation).md"
                    ],
                    "strategy": "hybrid",
                    "limit": 8,
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = load_acceptance_cases(cases_path)

    assert cases == (
        AcceptanceCase(
            case_id="rag",
            query="RAG 的流程是什麼？",
            expected_sources=("2-設計模式-08-RAG (Retrieval-Augmented Generation).md",),
            strategy="hybrid",
            limit=8,
        ),
    )


def test_cli_writes_report_and_returns_two_when_acceptance_fails(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    report_path = tmp_path / "report.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    "id": "message-queue",
                    "query": "Message Queue 適合用在哪些情境？",
                    "expected_sources": ["3-常用技術-07-Message Queue.md"],
                }
            ]
        ),
        encoding="utf-8",
    )

    def search(_case: AcceptanceCase) -> list[AcceptanceCandidate]:
        return []

    exit_code = main(
        ["--cases", str(cases_path), "--report", str(report_path)],
        search=search,
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["summary"] == {"total": 1, "passed": 0, "failed": 1}
