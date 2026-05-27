from app.background_jobs.service import (
    BACKGROUND_JOB_TASK_TYPES,
    TASK_DOCUMENT_REINDEX,
    TASK_EVAL_RUN,
    TASK_INDEX_REBUILD,
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
        TASK_INDEX_REBUILD,
        TASK_DOCUMENT_REINDEX,
        TASK_EVAL_RUN,
    }
