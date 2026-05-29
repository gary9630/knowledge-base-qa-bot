from sqlalchemy.engine import make_url
from sqlalchemy.engine.url import URL
from sqlalchemy.exc import ArgumentError

from app.core.config import Settings

POSTGRESQL_DEFAULT_PORT = 5432


def resolve_alembic_database_url(
    configured_url: str | None,
    settings: Settings | None = None,
) -> str:
    explicit_url = (configured_url or "").strip()
    if explicit_url:
        return explicit_url

    return (settings or Settings()).database_url


def validate_test_database_url(
    database_url: str,
    *,
    production_database_url: str,
) -> str | None:
    try:
        test_url = make_url(database_url)
        production_url = make_url(production_database_url)
    except (ArgumentError, ValueError):
        return "KB_DATABASE_URL_TEST must be a valid database URL"

    test_target = canonical_postgresql_target(test_url)
    production_target = canonical_postgresql_target(production_url)
    if test_target is None:
        return "KB_DATABASE_URL_TEST must use a PostgreSQL database URL"

    if production_target is None:
        return "KB_DATABASE_URL must use a PostgreSQL database URL"

    if test_target == production_target:
        return "KB_DATABASE_URL_TEST must not equal KB_DATABASE_URL"

    database_name = test_url.database or ""
    if "test" not in database_name.lower():
        return "KB_DATABASE_URL_TEST must point to an obvious test database"

    return None


def canonical_postgresql_target(url: URL) -> tuple[str, str | None, int, str] | None:
    dialect_family = url.drivername.split("+", maxsplit=1)[0]
    if dialect_family != "postgresql":
        return None

    return (
        dialect_family,
        url.host.lower() if url.host else None,
        url.port or POSTGRESQL_DEFAULT_PORT,
        url.database or "",
    )
