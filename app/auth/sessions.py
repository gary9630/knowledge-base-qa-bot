from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from app.core.config import Settings

PLATFORM_ROLE = "platform"


@dataclass(frozen=True)
class PlatformSession:
    username: str
    role: str
    csrf_token: str
    expires_at: int


def platform_auth_is_configured(settings: Settings) -> bool:
    return all(
        (
            settings.auth_secret_key,
            settings.platform_username,
            settings.platform_password,
        )
    )


def platform_auth_requires_configuration(settings: Settings) -> bool:
    return settings.app_env.lower() in {"production", "staging"}


def verify_platform_credentials(
    settings: Settings,
    *,
    username: str,
    password: str,
) -> bool:
    if not platform_auth_is_configured(settings):
        return False
    configured_username = settings.platform_username or ""
    configured_password = settings.platform_password or ""
    return secrets.compare_digest(username, configured_username) and secrets.compare_digest(
        password,
        configured_password,
    )


def create_platform_session_token(
    settings: Settings,
    *,
    username: str,
    csrf_token: str | None = None,
    now: int | None = None,
) -> str:
    secret = _required_auth_secret(settings)
    issued_at = _now(now)
    expires_at = issued_at + _session_ttl(settings)
    payload = {
        "sub": username,
        "role": PLATFORM_ROLE,
        "csrf": csrf_token or secrets.token_urlsafe(32),
        "exp": expires_at,
    }
    payload_segment = _base64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _sign(payload_segment, secret)
    return f"{payload_segment}.{signature}"


def verify_platform_session_token(
    settings: Settings,
    token: str,
    *,
    now: int | None = None,
) -> PlatformSession | None:
    secret = settings.auth_secret_key
    if not secret:
        return None

    try:
        payload_segment, signature = token.split(".", 1)
    except ValueError:
        return None

    expected_signature = _sign(payload_segment, secret)
    if not secrets.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(_base64url_decode(payload_segment))
    except (ValueError, json.JSONDecodeError):
        return None

    session = _session_from_payload(payload)
    if session is None or session.expires_at <= _now(now):
        return None
    return session


def _session_from_payload(payload: object) -> PlatformSession | None:
    if not isinstance(payload, dict):
        return None

    username = payload.get("sub")
    role = payload.get("role")
    csrf_token = payload.get("csrf")
    expires_at = payload.get("exp")
    if not isinstance(username, str) or not username:
        return None
    if role != PLATFORM_ROLE:
        return None
    if not isinstance(csrf_token, str) or not csrf_token:
        return None
    if not isinstance(expires_at, int):
        return None
    return PlatformSession(
        username=username,
        role=role,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


def _required_auth_secret(settings: Settings) -> str:
    if not settings.auth_secret_key:
        raise ValueError("KB_AUTH_SECRET_KEY is required for platform sessions.")
    return settings.auth_secret_key


def _session_ttl(settings: Settings) -> int:
    if settings.platform_session_ttl_seconds <= 0:
        raise ValueError("KB_PLATFORM_SESSION_TTL_SECONDS must be positive.")
    return settings.platform_session_ttl_seconds


def _sign(payload_segment: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload_segment.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(digest)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _now(value: int | None) -> int:
    return value if value is not None else int(time.time())
