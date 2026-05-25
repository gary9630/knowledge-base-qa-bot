from app.core.config import Settings
from app.core.database_urls import (
    resolve_alembic_database_url,
    validate_test_database_url,
)


def test_resolve_alembic_database_url_prefers_explicit_url() -> None:
    settings = Settings(database_url="postgresql+psycopg://kb:kb@db:5432/kb")

    resolved = resolve_alembic_database_url(
        "postgresql+psycopg://kb:kb@test-db:5432/kb_test",
        settings,
    )

    assert resolved == "postgresql+psycopg://kb:kb@test-db:5432/kb_test"


def test_resolve_alembic_database_url_uses_settings_for_blank_config() -> None:
    settings = Settings(database_url="postgresql+psycopg://kb:kb@db:5432/kb")

    resolved = resolve_alembic_database_url("", settings)

    assert resolved == settings.database_url


def test_validate_test_database_url_accepts_obvious_test_database() -> None:
    reason = validate_test_database_url(
        "postgresql+psycopg://kb:kb@localhost:5432/kb_test",
        production_database_url="postgresql+psycopg://kb:kb@localhost:5432/kb",
    )

    assert reason is None


def test_validate_test_database_url_rejects_production_database_name() -> None:
    reason = validate_test_database_url(
        "postgresql+psycopg://kb:kb@localhost:5432/kb",
        production_database_url="postgresql+psycopg://kb:kb@localhost:5432/kb_prod",
    )

    assert reason == "KB_DATABASE_URL_TEST must point to an obvious test database"


def test_validate_test_database_url_rejects_configured_app_database_url() -> None:
    database_url = "postgresql+psycopg://kb:kb@localhost:5432/kb_test"

    reason = validate_test_database_url(database_url, production_database_url=database_url)

    assert reason == "KB_DATABASE_URL_TEST must not equal KB_DATABASE_URL"


def test_validate_test_database_url_rejects_same_target_with_different_driver() -> None:
    reason = validate_test_database_url(
        "postgresql://kb:kb@localhost:5432/kb_test",
        production_database_url="postgresql+psycopg://kb:kb@localhost:5432/kb_test",
    )

    assert reason == "KB_DATABASE_URL_TEST must not equal KB_DATABASE_URL"


def test_validate_test_database_url_rejects_unsupported_test_database_dialect() -> None:
    reason = validate_test_database_url(
        "sqlite:///kb_test.db",
        production_database_url="postgresql+psycopg://kb:kb@localhost:5432/kb",
    )

    assert reason == "KB_DATABASE_URL_TEST must use a PostgreSQL database URL"


def test_validate_test_database_url_normalizes_postgresql_default_port() -> None:
    reason = validate_test_database_url(
        "postgresql://kb:kb@localhost/kb_test",
        production_database_url="postgresql+psycopg://kb:kb@localhost:5432/kb_test",
    )

    assert reason == "KB_DATABASE_URL_TEST must not equal KB_DATABASE_URL"
