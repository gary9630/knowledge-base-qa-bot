from app.evals.reporting import empty_eval_report


def test_empty_eval_report_has_zero_totals() -> None:
    report = empty_eval_report()

    assert report["totals"] == {
        "total_cases": 0,
        "active_cases": 0,
        "total_runs": 0,
        "cases_by_source_kind": {},
    }
    assert report["latest_run"] is None
    assert report["recent_runs"] == []
    assert report["latest_failures"] == []
    assert report["worst_cases"] == []
