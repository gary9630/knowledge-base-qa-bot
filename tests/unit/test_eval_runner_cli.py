from uuid import uuid4

from app.evals.runner import EvalRunExecution, EvalRunOptions
from scripts.run_evals import main


def test_run_evals_cli_exits_zero_when_regressions_are_allowed() -> None:
    calls: list[EvalRunOptions] = []

    def runner(options: EvalRunOptions) -> EvalRunExecution:
        calls.append(options)
        return EvalRunExecution(
            run_id=uuid4(),
            status="succeeded",
            stats={"total": 2, "passed": 1, "failed": 1, "pass_rate": 0.5},
        )

    exit_code = main(["--trigger", "scheduled"], runner=runner)

    assert exit_code == 0
    assert calls == [EvalRunOptions(trigger="scheduled", strategy="hybrid", limit=5)]


def test_run_evals_cli_exits_two_when_fail_on_regression_is_enabled() -> None:
    def runner(options: EvalRunOptions) -> EvalRunExecution:
        return EvalRunExecution(
            run_id=uuid4(),
            status="succeeded",
            stats={"total": 2, "passed": 1, "failed": 1, "pass_rate": 0.5},
        )

    exit_code = main(["--fail-on-regression"], runner=runner)

    assert exit_code == 2
