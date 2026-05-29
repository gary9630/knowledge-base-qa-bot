from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from app.ingestion import pipeline as pipeline_module
from app.ingestion.pipeline import (
    IngestionPipeline,
    IngestionRetryNotAllowedError,
    InMemoryIngestionJobStore,
)
from app.ingestion.validation import IngestionValidationError

IMPORTED_AT = "2026-05-26T12:00:00+00:00"


def test_ingestion_pipeline_writes_artifacts_and_succeeded_job(tmp_path: Path) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )

    result = pipeline.import_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=b"Question\n\nAnswer",
        imported_at=IMPORTED_AT,
    )

    assert result.job.status == "succeeded"
    assert result.job.filename == "guide.txt"
    assert result.job.size_bytes == len(b"Question\n\nAnswer")
    assert result.job.raw_path is not None
    assert Path(result.job.raw_path).read_bytes() == b"Question\n\nAnswer"
    assert result.job.canonical_path is not None
    canonical = Path(result.job.canonical_path).read_text(encoding="utf-8")
    assert "source_original: raw/guide.txt" in canonical
    assert f"content_hash: {result.job.content_hash}" in canonical
    assert "canonical_path:" in canonical


def test_ingestion_pipeline_deduplicates_same_content_without_rewriting(
    tmp_path: Path,
) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )

    first = pipeline.import_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=b"Same body",
        imported_at=IMPORTED_AT,
    )
    second = pipeline.import_upload(
        filename="copy.txt",
        content_type="text/plain",
        body=b"Same body",
        imported_at=IMPORTED_AT,
    )

    assert second.job.status == "duplicate"
    assert second.job.canonical_path == first.job.canonical_path
    assert second.job.raw_path == first.job.raw_path
    assert second.job.metadata["duplicate_of"] == str(first.job.id)
    assert not (tmp_path / "raw" / "copy.txt").exists()
    assert not (tmp_path / "docs" / "copy.md").exists()


def test_async_ingestion_deduplicates_same_content_while_original_is_queued(
    tmp_path: Path,
) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )

    first = pipeline.queue_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=b"Same body",
    )
    second = pipeline.queue_upload(
        filename="copy.txt",
        content_type="text/plain",
        body=b"Same body",
    )

    assert first.job.status == "queued"
    assert second.job.status == "duplicate"
    assert second.job.canonical_path == first.job.canonical_path
    assert second.job.raw_path == first.job.raw_path
    assert second.job.metadata["duplicate_of"] == str(first.job.id)
    assert not (tmp_path / "raw" / "copy.txt").exists()
    assert not (tmp_path / "docs" / "copy.md").exists()


def test_queue_upload_rejects_empty_files_before_raw_write(tmp_path: Path) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )

    with pytest.raises(IngestionValidationError, match="empty"):
        pipeline.queue_upload(
            filename="empty.txt",
            content_type="text/plain",
            body=b"",
        )

    assert store.list_recent(limit=1) == []
    assert not (tmp_path / "raw").exists()


def test_queue_upload_rejects_pdf_without_pdf_signature(tmp_path: Path) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )

    with pytest.raises(IngestionValidationError, match="PDF"):
        pipeline.queue_upload(
            filename="guide.pdf",
            content_type="application/pdf",
            body=b"not a pdf",
        )

    assert store.list_recent(limit=1) == []
    assert not (tmp_path / "raw").exists()


def test_async_ingestion_versions_same_filename_with_different_content(
    tmp_path: Path,
) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )

    first = pipeline.queue_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=b"First body",
    )
    second_body = b"Different body"
    second = pipeline.queue_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=second_body,
    )
    expected_suffix = sha256(second_body).hexdigest()[:12]

    assert first.job.status == "queued"
    assert second.job.status == "queued"
    assert second.job.raw_path is not None
    assert second.job.canonical_path is not None
    assert Path(second.job.raw_path).name == f"guide-{expected_suffix}.txt"
    assert Path(second.job.canonical_path).name == f"guide-{expected_suffix}.md"
    assert Path(second.job.raw_path).read_bytes() == second_body
    assert second.job.metadata["path_strategy"] == "content_hash_suffix"
    assert second.job.metadata["original_filename"] == "guide.txt"
    assert second.job.metadata["raw_filename"] == f"guide-{expected_suffix}.txt"
    assert second.job.metadata["canonical_filename"] == f"guide-{expected_suffix}.md"


def test_run_queued_job_records_conversion_diagnostics(tmp_path: Path) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )
    queued = pipeline.queue_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=b"Question\n\nAnswer",
    )

    result = pipeline.run_queued_job(job_id=queued.job.id, imported_at=IMPORTED_AT)

    assert result.job.status == "succeeded"
    assert result.job.metadata["detected_file_type"] == "text"
    assert result.job.metadata["original_filename"] == "guide.txt"
    assert result.job.metadata["canonical_filename"] == "guide.md"
    assert result.job.metadata["raw_filename"] == "guide.txt"
    assert isinstance(result.job.metadata["markdown_bytes"], int)
    assert result.job.metadata["markdown_bytes"] > 0
    assert result.job.metadata["processed_async"] is True


def test_async_ingestion_only_processes_queued_jobs(tmp_path: Path) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )
    queued = pipeline.queue_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=b"Body",
    )
    store.mark_running(queued.job.id)

    with pytest.raises(IngestionRetryNotAllowedError, match="Only queued import jobs"):
        pipeline.run_queued_job(job_id=queued.job.id, imported_at=IMPORTED_AT)

    assert not (tmp_path / "docs" / "guide.md").exists()


def test_ingestion_pipeline_keeps_failed_raw_upload_for_retry(tmp_path: Path) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )

    with pytest.raises(UnicodeDecodeError):
        pipeline.import_upload(
            filename="broken.txt",
            content_type="text/plain",
            body=b"\xff\xfe",
            imported_at=IMPORTED_AT,
        )

    failed_job = store.list_recent(limit=1)[0]
    assert failed_job.status == "failed"
    assert failed_job.raw_path is not None
    assert Path(failed_job.raw_path).read_bytes() == b"\xff\xfe"
    assert failed_job.canonical_path is not None
    assert not Path(failed_job.canonical_path).exists()
    assert "UnicodeDecodeError" in (failed_job.error or "")


def test_ingestion_pipeline_can_retry_failed_job_after_transient_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )

    def fail_once(*args: object, **kwargs: object) -> str:
        raise RuntimeError("temporary parser outage")

    monkeypatch.setattr(pipeline_module, "import_file_to_markdown", fail_once)
    with pytest.raises(RuntimeError, match="temporary parser outage"):
        pipeline.import_upload(
            filename="guide.txt",
            content_type="text/plain",
            body=b"Body",
            imported_at=IMPORTED_AT,
        )

    failed_job = store.list_recent(limit=1)[0]
    monkeypatch.setattr(
        pipeline_module,
        "import_file_to_markdown",
        lambda *args, **kwargs: "# guide\n\nBody\n",
    )

    result = pipeline.retry_failed_job(job_id=failed_job.id, imported_at=IMPORTED_AT)

    assert result.job.status == "succeeded"
    assert result.job.metadata["retried"] is True
    assert result.job.canonical_path is not None
    assert Path(result.job.canonical_path).read_text(encoding="utf-8") == "# guide\n\nBody\n"


def test_ingestion_pipeline_marks_raw_write_failure_as_failed_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )
    original_write_bytes = Path.write_bytes

    def fail_raw_write(path: Path, data: bytes) -> int:
        if path.name == "guide.txt":
            raise PermissionError("raw volume is read-only")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_raw_write)

    with pytest.raises(PermissionError, match="raw volume is read-only"):
        pipeline.import_upload(
            filename="guide.txt",
            content_type="text/plain",
            body=b"Body",
            imported_at=IMPORTED_AT,
        )

    failed_job = store.list_recent(limit=1)[0]
    assert failed_job.status == "failed"
    assert "PermissionError" in (failed_job.error or "")
    assert failed_job.raw_path is not None
    assert failed_job.canonical_path is not None


def test_ingestion_pipeline_retry_marks_missing_raw_artifact_as_failed(
    tmp_path: Path,
) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )
    with pytest.raises(UnicodeDecodeError):
        pipeline.import_upload(
            filename="broken.txt",
            content_type="text/plain",
            body=b"\xff\xfe",
            imported_at=IMPORTED_AT,
        )
    failed_job = store.list_recent(limit=1)[0]
    assert failed_job.raw_path is not None
    Path(failed_job.raw_path).unlink()

    with pytest.raises(IngestionRetryNotAllowedError, match="Raw artifact is not readable"):
        pipeline.retry_failed_job(job_id=failed_job.id, imported_at=IMPORTED_AT)

    retried_job = store.get(failed_job.id)
    assert retried_job is not None
    assert retried_job.status == "failed"
    assert "FileNotFoundError" in (retried_job.error or "")


def test_ingestion_pipeline_versions_same_destination_with_different_content(
    tmp_path: Path,
) -> None:
    store = InMemoryIngestionJobStore()
    pipeline = IngestionPipeline(
        store=store,
        raw_dir=tmp_path / "raw",
        docs_dir=tmp_path / "docs",
    )
    pipeline.import_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=b"First body",
        imported_at=IMPORTED_AT,
    )
    second_body = b"Different body"

    second = pipeline.import_upload(
        filename="guide.txt",
        content_type="text/plain",
        body=second_body,
        imported_at=IMPORTED_AT,
    )
    expected_suffix = sha256(second_body).hexdigest()[:12]

    assert second.job.status == "succeeded"
    assert second.job.raw_path is not None
    assert second.job.canonical_path is not None
    assert Path(second.job.raw_path).name == f"guide-{expected_suffix}.txt"
    assert Path(second.job.canonical_path).name == f"guide-{expected_suffix}.md"
    assert Path(second.job.raw_path).read_bytes() == second_body
    assert Path(second.job.canonical_path).exists()
