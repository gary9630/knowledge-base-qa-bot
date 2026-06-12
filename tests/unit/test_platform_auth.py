from __future__ import annotations

from app.auth.sessions import (
    create_platform_session_token,
    platform_auth_is_configured,
    platform_auth_requires_configuration,
    verify_platform_credentials,
    verify_platform_session_token,
)
from app.core.config import Settings


def test_platform_session_token_round_trips() -> None:
    settings = _settings()

    token = create_platform_session_token(
        settings,
        username="student",
        csrf_token="csrf-token",
        now=100,
    )
    session = verify_platform_session_token(settings, token, now=101)

    assert session is not None
    assert session.username == "student"
    assert session.role == "student"
    assert session.csrf_token == "csrf-token"
    assert session.expires_at == 100 + settings.platform_session_ttl_seconds


def test_platform_session_token_round_trips_admin_role() -> None:
    settings = _settings()

    token = create_platform_session_token(
        settings,
        username="prof",
        role="admin",
        now=100,
    )
    session = verify_platform_session_token(settings, token, now=101)

    assert session is not None
    assert session.role == "admin"


def test_platform_session_token_rejects_tampering() -> None:
    settings = _settings()
    token = create_platform_session_token(settings, username="student", now=100)
    payload, signature = token.split(".", 1)

    tampered = f"{payload[:-1]}x.{signature}"

    assert verify_platform_session_token(settings, tampered, now=101) is None


def test_platform_session_token_rejects_expiry() -> None:
    settings = _settings(platform_session_ttl_seconds=10)
    token = create_platform_session_token(settings, username="student", now=100)

    assert verify_platform_session_token(settings, token, now=111) is None


def test_platform_auth_configuration_detection() -> None:
    assert platform_auth_is_configured(_settings()) is True
    assert (
        platform_auth_is_configured(
            _settings(
                platform_username=None,
                platform_password=None,
                admin_username=None,
                admin_password=None,
            )
        )
        is False
    )
    assert platform_auth_requires_configuration(Settings(app_env="production")) is True
    assert platform_auth_requires_configuration(Settings(app_env="staging")) is True
    assert platform_auth_requires_configuration(Settings(app_env="development")) is False


def test_verify_platform_credentials_maps_accounts_to_roles() -> None:
    settings = _settings()

    assert verify_platform_credentials(settings, username="student", password="pass") == "student"
    assert verify_platform_credentials(settings, username="prof", password="admin-pass") == "admin"
    assert verify_platform_credentials(settings, username="admin", password="pass") is None
    assert verify_platform_credentials(settings, username="student", password="wrong") is None


def test_verify_platform_credentials_with_admin_only_configuration() -> None:
    settings = _settings(platform_username=None, platform_password=None)

    assert platform_auth_is_configured(settings) is True
    assert verify_platform_credentials(settings, username="prof", password="admin-pass") == "admin"
    assert verify_platform_credentials(settings, username="student", password="pass") is None


def _settings(
    *,
    auth_secret_key: str | None = "test-secret",
    platform_username: str | None = "student",
    platform_password: str | None = "pass",
    admin_username: str | None = "prof",
    admin_password: str | None = "admin-pass",
    platform_session_ttl_seconds: int = 86_400,
) -> Settings:
    return Settings(
        auth_secret_key=auth_secret_key,
        platform_username=platform_username,
        platform_password=platform_password,
        admin_username=admin_username,
        admin_password=admin_password,
        platform_session_ttl_seconds=platform_session_ttl_seconds,
        embedding_provider="fake",
        answer_provider="fake",
    )
