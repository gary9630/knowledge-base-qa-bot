from __future__ import annotations

import argparse
import sys
import time
from typing import Protocol

from app.background_jobs.worker import BackgroundWorker
from app.core.config import Settings


class ProcessedJob(Protocol):
    @property
    def id(self) -> object: ...

    @property
    def task_type(self) -> str: ...

    @property
    def status(self) -> str: ...


class WorkerRunner(Protocol):
    def run_once(self) -> ProcessedJob | None: ...

    def shutdown(self) -> None: ...


def main(
    argv: list[str] | None = None,
    *,
    worker: WorkerRunner | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Run background jobs from the DB queue.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job.")
    parser.add_argument("--poll-seconds", type=float, default=None)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--worker-id", type=str, default=None)
    namespace = parser.parse_args(argv)
    settings = Settings()
    poll_seconds = (
        float(namespace.poll_seconds)
        if namespace.poll_seconds is not None
        else float(settings.worker_heartbeat_interval_seconds)
    )

    if poll_seconds < 0:
        print("--poll-seconds must be non-negative", file=sys.stderr)
        return 2
    if namespace.max_jobs is not None and namespace.max_jobs < 1:
        print("--max-jobs must be at least 1", file=sys.stderr)
        return 2

    resolved_worker = worker or BackgroundWorker(settings=settings, worker_id=namespace.worker_id)
    processed = 0

    try:
        while True:
            job = resolved_worker.run_once()
            if job is None:
                print("no queued jobs")
                if namespace.once or namespace.max_jobs is not None:
                    return 0
                time.sleep(poll_seconds)
                continue

            processed += 1
            print(
                "processed job "
                f"{job.id} "
                f"({job.task_type}) "
                f"status={job.status}"
            )
            if namespace.once or (
                namespace.max_jobs is not None and processed >= namespace.max_jobs
            ):
                return 0
    except KeyboardInterrupt:
        print("worker shutdown requested")
        return 0
    finally:
        try:
            resolved_worker.shutdown()
        except Exception as error:  # pragma: no cover - defensive shutdown path
            print(f"worker shutdown heartbeat failed: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
