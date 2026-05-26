from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.indexing import (
    index_ready_check,
    migration_ready_check,
    pgvector_ready_check,
)


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
