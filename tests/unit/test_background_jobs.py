from datetime import UTC, datetime, timedelta

from app.api.jobs import background_job_is_stale
from app.background_jobs.service import (
    BACKGROUND_JOB_TASK_TYPES,
    TASK_DOCUMENT_REINDEX,
    TASK_EVAL_RUN,
    TASK_INDEX_REBUILD,
    TASK_INGEST_UPLOAD,
)
from app.models import BackgroundJob


def test_background_job_defaults_are_available_before_flush() -> None:
    job = BackgroundJob(task_type=TASK_INDEX_REBUILD)

    assert job.task_type == TASK_INDEX_REBUILD
    assert job.status == "queued"
    assert job.priority == 100
    assert job.attempts == 0
    assert job.max_attempts == 3
    assert job.payload_json == {}
    assert job.result_json == {}
    assert job.error is None
    assert job.locked_by is None


def test_background_job_task_contract_is_explicit() -> None:
    assert BACKGROUND_JOB_TASK_TYPES == {
        TASK_INGEST_UPLOAD,
        TASK_INDEX_REBUILD,
        TASK_DOCUMENT_REINDEX,
        TASK_EVAL_RUN,
    }


def test_background_job_stale_marker_uses_running_lock_age() -> None:
    stale_job = BackgroundJob(task_type=TASK_INDEX_REBUILD)
    stale_job.status = "running"
    stale_job.locked_at = datetime.now(UTC) - timedelta(seconds=120)

    queued_job = BackgroundJob(task_type=TASK_INDEX_REBUILD)
    queued_job.status = "queued"
    queued_job.locked_at = datetime.now(UTC) - timedelta(seconds=120)

    assert background_job_is_stale(stale_job, stale_after_seconds=60) is True
    assert background_job_is_stale(stale_job, stale_after_seconds=300) is False
    assert background_job_is_stale(queued_job, stale_after_seconds=60) is False
