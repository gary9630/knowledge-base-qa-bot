import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    database_url = os.getenv("KB_DATABASE_URL_TEST")
    if not database_url:
        pytest.skip("KB_DATABASE_URL_TEST is not configured")

    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
