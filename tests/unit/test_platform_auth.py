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
    assert session.role == "platform"
    assert session.csrf_token == "csrf-token"
    assert session.expires_at == 100 + settings.platform_session_ttl_seconds


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
    assert platform_auth_is_configured(Settings(auth_secret_key="secret")) is False
    assert platform_auth_requires_configuration(Settings(app_env="production")) is True
    assert platform_auth_requires_configuration(Settings(app_env="staging")) is True
    assert platform_auth_requires_configuration(Settings(app_env="development")) is False


def test_verify_platform_credentials_uses_configured_single_user() -> None:
    settings = _settings()

    assert verify_platform_credentials(settings, username="student", password="pass") is True
    assert verify_platform_credentials(settings, username="admin", password="pass") is False
    assert verify_platform_credentials(settings, username="student", password="wrong") is False


def _settings(
    *,
    auth_secret_key: str | None = "test-secret",
    platform_username: str | None = "student",
    platform_password: str | None = "pass",
    platform_session_ttl_seconds: int = 86_400,
) -> Settings:
    return Settings(
        auth_secret_key=auth_secret_key,
        platform_username=platform_username,
        platform_password=platform_password,
        platform_session_ttl_seconds=platform_session_ttl_seconds,
        embedding_provider="fake",
        answer_provider="fake",
    )
