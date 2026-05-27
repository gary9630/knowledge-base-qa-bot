from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.indexing import (
    index_ready_check,
    migration_ready_check,
    pgvector_ready_check,
    storage_ready_check,
)
from app.core.config import Settings


@pytest.fixture
def sqlite_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def test_pgvector_ready_check_reports_query_failure(sqlite_session: Session) -> None:
    check = pgvector_ready_check(sqlite_session)

    assert check.ok is False
    assert check.detail == "pgvector readiness check failed: OperationalError"


def test_migration_ready_check_reports_query_failure(sqlite_session: Session) -> None:
    check = migration_ready_check(sqlite_session)

    assert check.ok is False
    assert check.detail == "Migration readiness check failed: OperationalError"


def test_index_ready_check_reports_query_failure(sqlite_session: Session) -> None:
    check = index_ready_check(sqlite_session)

    assert check.ok is False
    assert check.detail == "Index readiness check failed: OperationalError"


def test_storage_ready_check_passes_when_paths_are_existing_or_creatable(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path
    docs_dir = base_dir / "docs"
    docs_dir.mkdir()
    settings = Settings(
        docs_dir=str(docs_dir),
        raw_dir=str(base_dir / "raw"),
        kb_dir=str(base_dir / ".kb"),
    )

    check = storage_ready_check(settings)

    assert check.ok is True
    assert check.detail == "Storage paths are writable or creatable."


def test_storage_ready_check_requires_docs_dir_to_exist(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path
    settings = Settings(
        docs_dir=str(base_dir / "missing-docs"),
        raw_dir=str(base_dir / "raw"),
        kb_dir=str(base_dir / ".kb"),
    )

    check = storage_ready_check(settings)

    assert check.ok is False
    assert "docs_dir does not exist" in str(check.detail)


def test_storage_ready_check_rejects_file_paths(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path
    docs_dir = base_dir / "docs"
    docs_dir.mkdir()
    raw_file = base_dir / "raw"
    raw_file.write_text("not a directory", encoding="utf-8")
    settings = Settings(
        docs_dir=str(docs_dir),
        raw_dir=str(raw_file),
        kb_dir=str(base_dir / ".kb"),
    )

    check = storage_ready_check(settings)

    assert check.ok is False
    assert "raw_dir is not a directory" in str(check.detail)
