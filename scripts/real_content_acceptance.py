from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import SessionLocal
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.models import RetrievalStrategy, RetrievedCandidate


@dataclass(frozen=True)
class AcceptanceCase:
    case_id: str
    query: str
    expected_sources: tuple[str, ...]
    strategy: RetrievalStrategy = "hybrid"
    limit: int = 5


@dataclass(frozen=True)
class AcceptanceCandidate:
    source_id: str
    filename: str
    heading: str
    score: float
    strategy: str

    @classmethod
    def from_retrieved(cls, candidate: RetrievedCandidate) -> AcceptanceCandidate:
        return cls(
            source_id=candidate.source_id,
            filename=candidate.filename,
            heading=candidate.heading,
            score=candidate.score,
            strategy=candidate.strategy,
        )


@dataclass(frozen=True)
class AcceptanceCaseResult:
    case_id: str
    query: str
    status: str
    expected_sources: tuple[str, ...]
    matched_sources: tuple[str, ...]
    retrieved_sources: tuple[str, ...]
    top_score: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceReport:
    status: str
    summary: dict[str, int]
    cases: tuple[AcceptanceCaseResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": dict(self.summary),
            "cases": [case.to_dict() for case in self.cases],
        }


AcceptanceSearch = Callable[[AcceptanceCase], Sequence[AcceptanceCandidate]]
SessionFactory = Callable[[], Session]


def load_acceptance_cases(path: Path) -> tuple[AcceptanceCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Acceptance cases file must contain a JSON list.")

    cases: list[AcceptanceCase] = []
    for index, raw_case in enumerate(payload):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Acceptance case at index {index} must be an object.")
        case_id = str(raw_case.get("id") or raw_case.get("case_id") or "").strip()
        query = str(raw_case.get("query") or "").strip()
        expected_sources = raw_case.get("expected_sources")
        strategy = str(raw_case.get("strategy") or "hybrid")
        limit = int(raw_case.get("limit") or 5)
        if not case_id:
            raise ValueError(f"Acceptance case at index {index} is missing id.")
        if not query:
            raise ValueError(f"Acceptance case {case_id} is missing query.")
        if not isinstance(expected_sources, list) or not expected_sources:
            raise ValueError(f"Acceptance case {case_id} must define expected_sources.")
        if strategy not in {"lexical", "markdown", "vector", "hybrid"}:
            raise ValueError(f"Acceptance case {case_id} has unsupported strategy: {strategy}")
        if limit <= 0:
            raise ValueError(f"Acceptance case {case_id} limit must be positive.")
        cases.append(
            AcceptanceCase(
                case_id=case_id,
                query=query,
                expected_sources=tuple(str(source) for source in expected_sources),
                strategy=cast(RetrievalStrategy, strategy),
                limit=limit,
            )
        )
    return tuple(cases)


def evaluate_case(
    case: AcceptanceCase,
    candidates: Sequence[AcceptanceCandidate],
) -> AcceptanceCaseResult:
    matched_sources = tuple(
        expected
        for expected in case.expected_sources
        if any(_source_matches(candidate, expected) for candidate in candidates)
    )
    retrieved_sources = tuple(candidate.source_id for candidate in candidates)
    top_score = candidates[0].score if candidates else None
    return AcceptanceCaseResult(
        case_id=case.case_id,
        query=case.query,
        status="passed" if matched_sources else "failed",
        expected_sources=case.expected_sources,
        matched_sources=matched_sources,
        retrieved_sources=retrieved_sources,
        top_score=top_score,
    )


def run_acceptance_cases(
    cases: Sequence[AcceptanceCase],
    *,
    search: AcceptanceSearch,
) -> AcceptanceReport:
    case_results = tuple(evaluate_case(case, search(case)) for case in cases)
    passed = sum(1 for result in case_results if result.status == "passed")
    failed = len(case_results) - passed
    return AcceptanceReport(
        status="passed" if failed == 0 else "failed",
        summary={"total": len(case_results), "passed": passed, "failed": failed},
        cases=case_results,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    search: AcceptanceSearch | None = None,
    settings: Settings | None = None,
    session_factory: SessionFactory | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Run retrieval acceptance checks against real course content."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("ops/real-content-acceptance-cases.json"),
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--visibility-label",
        action="append",
        dest="visibility_labels",
        default=["public"],
        help="Visibility labels to include during retrieval; can be repeated.",
    )
    namespace = parser.parse_args(argv)

    try:
        cases = load_acceptance_cases(namespace.cases)
        resolved_search = search or _searcher_from_dependencies(
            settings=settings,
            session_factory=session_factory,
            embedding_provider=embedding_provider,
            visibility_labels=tuple(namespace.visibility_labels),
        )
        report = run_acceptance_cases(cases, search=resolved_search)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    payload = report.to_dict()
    output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if namespace.report is not None:
        namespace.report.parent.mkdir(parents=True, exist_ok=True)
        namespace.report.write_text(f"{output}\n", encoding="utf-8")
    print(output)
    return 0 if report.status == "passed" else 2


def _searcher_from_dependencies(
    *,
    settings: Settings | None,
    session_factory: SessionFactory | None,
    embedding_provider: EmbeddingProvider | None,
    visibility_labels: tuple[str, ...],
) -> AcceptanceSearch:
    resolved_settings = settings or Settings()
    resolved_session_factory = session_factory or SessionLocal
    resolved_embedding_provider = embedding_provider or create_embedding_provider(
        resolved_settings
    )

    def search(case: AcceptanceCase) -> tuple[AcceptanceCandidate, ...]:
        with resolved_session_factory() as session:
            retriever = HybridRetriever(
                session=session,
                embedding_provider=resolved_embedding_provider,
                visibility_labels=visibility_labels,
            )
            result = retriever.search(
                case.query,
                strategy=case.strategy,
                limit=case.limit,
                debug=True,
            )
            return tuple(
                AcceptanceCandidate.from_retrieved(candidate)
                for candidate in result.candidates
            )

    return search


def _source_matches(candidate: AcceptanceCandidate, expected_source: str) -> bool:
    expected = expected_source.casefold()
    return expected in candidate.filename.casefold() or expected in candidate.source_id.casefold()


if __name__ == "__main__":
    raise SystemExit(main())
