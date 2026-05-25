from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import Settings


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
    except ArgumentError:
        return "KB_DATABASE_URL_TEST must be a valid database URL"

    if test_url.render_as_string(hide_password=False) == production_url.render_as_string(
        hide_password=False
    ):
        return "KB_DATABASE_URL_TEST must not equal KB_DATABASE_URL"

    database_name = test_url.database or ""
    if "test" not in database_name.lower():
        return "KB_DATABASE_URL_TEST must point to an obvious test database"

    return None
