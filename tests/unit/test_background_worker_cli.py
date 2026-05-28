from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from scripts.run_background_worker import ProcessedJob, main


@dataclass(frozen=True)
class StubProcessedJob:
    id: UUID
    task_type: str
    status: str


class StubWorker:
    def __init__(self, jobs: list[ProcessedJob | None]) -> None:
        self.jobs = jobs
        self.calls = 0
        self.shutdown_called = False

    def run_once(self) -> ProcessedJob | None:
        self.calls += 1
        if not self.jobs:
            return None
        return self.jobs.pop(0)

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_background_worker_cli_once_exits_zero_after_processing_job(
    capsys: pytest.CaptureFixture[str],
) -> None:
    job_id = uuid4()
    worker = StubWorker(
        [
            StubProcessedJob(
                id=job_id,
                task_type="index.rebuild",
                status="succeeded",
            )
        ]
    )

    exit_code = main(["--once"], worker=worker)

    assert exit_code == 0
    assert worker.calls == 1
    assert f"processed job {job_id}" in capsys.readouterr().out


def test_background_worker_cli_once_reports_when_queue_is_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    worker = StubWorker([None])

    exit_code = main(["--once"], worker=worker)

    assert exit_code == 0
    assert "no queued jobs" in capsys.readouterr().out


def test_background_worker_cli_respects_max_jobs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    worker = StubWorker(
        [
            StubProcessedJob(id=uuid4(), task_type="index.rebuild", status="succeeded"),
            StubProcessedJob(id=uuid4(), task_type="eval.run", status="succeeded"),
            StubProcessedJob(id=uuid4(), task_type="document.reindex", status="succeeded"),
        ]
    )

    exit_code = main(["--max-jobs", "2", "--poll-seconds", "0"], worker=worker)

    assert exit_code == 0
    assert worker.calls == 2
    assert capsys.readouterr().out.count("processed job") == 2
    assert worker.shutdown_called is True
