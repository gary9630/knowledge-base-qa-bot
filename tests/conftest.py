import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database_urls import validate_test_database_url


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    database_url = os.getenv("KB_DATABASE_URL_TEST")
    if not database_url:
        pytest.skip("KB_DATABASE_URL_TEST is not configured")

    safety_reason = validate_test_database_url(
        database_url,
        production_database_url=Settings().database_url,
    )
    if safety_reason:
        pytest.skip(safety_reason)

    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        # Keep app-level commit/rollback inside a SAVEPOINT so fixture rollback
        # still isolates DB-backed integration tests.
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
