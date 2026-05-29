from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.tables import EvalCase, EvalResult, EvalRun


def empty_eval_report() -> dict[str, Any]:
    return {
        "totals": {
            "total_cases": 0,
            "active_cases": 0,
            "total_runs": 0,
            "cases_by_source_kind": {},
        },
        "latest_run": None,
        "recent_runs": [],
        "latest_failures": [],
        "worst_cases": [],
    }


def build_eval_report(
    session: Session,
    *,
    recent_limit: int = 10,
    failure_limit: int = 10,
) -> dict[str, Any]:
    report = empty_eval_report()
    report["totals"] = {
        "total_cases": _count_cases(session),
        "active_cases": _count_active_cases(session),
        "total_runs": _count_runs(session),
        "cases_by_source_kind": _cases_by_source_kind(session),
    }

    recent_runs = list(
        session.scalars(
            select(EvalRun)
            .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
            .limit(recent_limit)
        ).all()
    )
    report["recent_runs"] = [_run_summary(run) for run in recent_runs]

    latest_run = session.scalar(
        select(EvalRun)
        .options(selectinload(EvalRun.results).selectinload(EvalResult.case))
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .limit(1)
    )
    if latest_run is not None:
        report["latest_run"] = _run_summary(latest_run)
        report["latest_failures"] = [
            _result_summary(result)
            for result in sorted(latest_run.results, key=lambda item: (item.created_at, item.id))
            if not result.passed
        ][:failure_limit]

    report["worst_cases"] = _worst_cases(session, limit=failure_limit)
    return report


def _count_cases(session: Session) -> int:
    return int(session.scalar(select(func.count(EvalCase.id))) or 0)


def _count_runs(session: Session) -> int:
    return int(session.scalar(select(func.count(EvalRun.id))) or 0)


def _count_active_cases(session: Session) -> int:
    return int(
        session.scalar(select(func.count(EvalCase.id)).where(EvalCase.active.is_(True))) or 0
    )


def _cases_by_source_kind(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(EvalCase.source_kind, func.count(EvalCase.id)).group_by(EvalCase.source_kind)
    ).all()
    return {str(source_kind): int(count) for source_kind, count in rows}


def _run_summary(run: EvalRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "status": run.status,
        "trigger": run.trigger,
        "strategy": run.strategy,
        "limit": run.limit,
        "stats": dict(run.stats_json),
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _result_summary(result: EvalResult) -> dict[str, Any]:
    return {
        "id": str(result.id),
        "case_id": str(result.case_id),
        "name": result.case.name if result.case is not None else "",
        "query": result.query,
        "expected_decision": result.expected_decision,
        "actual_decision": result.actual_decision,
        "passed": result.passed,
        "score": result.score,
        "expected_source_ids": list(result.expected_sources_json),
        "selected_source_ids": list(result.selected_sources_json),
        "cited_source_ids": list(result.cited_sources_json),
        "missing_source_ids": list(result.missing_sources_json),
        "unexpected_source_ids": list(result.unexpected_sources_json),
        "metrics": dict(result.metrics_json),
        "error": result.error,
    }


def _worst_cases(session: Session, *, limit: int) -> list[dict[str, Any]]:
    results = list(
        session.scalars(
            select(EvalResult)
            .options(selectinload(EvalResult.case))
            .order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
            .limit(500)
        ).all()
    )
    cases: dict[str, dict[str, Any]] = {}
    for result in results:
        key = str(result.case_id)
        entry = cases.setdefault(
            key,
            {
                "case_id": key,
                "name": result.case.name if result.case is not None else "",
                "query": result.query,
                "total": 0,
                "failed": 0,
                "pass_rate": 0.0,
            },
        )
        entry["total"] += 1
        if not result.passed:
            entry["failed"] += 1

    for entry in cases.values():
        total = int(entry["total"])
        failed = int(entry["failed"])
        entry["pass_rate"] = (total - failed) / total if total > 0 else 0.0

    return sorted(
        cases.values(),
        key=lambda item: (-int(item["failed"]), float(item["pass_rate"]), str(item["name"])),
    )[:limit]
