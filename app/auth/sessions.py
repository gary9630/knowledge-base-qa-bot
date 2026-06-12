from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from app.core.config import Settings

# Legacy role kept for tokens issued before student/admin roles existed.
PLATFORM_ROLE = "platform"
ROLE_STUDENT = "student"
ROLE_ADMIN = "admin"
VALID_ROLES = {ROLE_STUDENT, ROLE_ADMIN}


@dataclass(frozen=True)
class PlatformSession:
    username: str
    role: str
    csrf_token: str
    expires_at: int


def _student_account_configured(settings: Settings) -> bool:
    return bool(settings.platform_username and settings.platform_password)


def _admin_account_configured(settings: Settings) -> bool:
    return bool(settings.admin_username and settings.admin_password)


def platform_auth_is_configured(settings: Settings) -> bool:
    return bool(settings.auth_secret_key) and (
        _student_account_configured(settings) or _admin_account_configured(settings)
    )


def platform_auth_requires_configuration(settings: Settings) -> bool:
    return settings.app_env.lower() in {"production", "staging"}


def verify_platform_credentials(
    settings: Settings,
    *,
    username: str,
    password: str,
) -> str | None:
    """Return the role for valid credentials, or None when they do not match."""
    if not platform_auth_is_configured(settings):
        return None

    if _student_account_configured(settings) and _credentials_match(
        username,
        password,
        settings.platform_username or "",
        settings.platform_password or "",
    ):
        return ROLE_STUDENT

    if _admin_account_configured(settings) and _credentials_match(
        username,
        password,
        settings.admin_username or "",
        settings.admin_password or "",
    ):
        return ROLE_ADMIN

    return None


def _credentials_match(
    username: str,
    password: str,
    configured_username: str,
    configured_password: str,
) -> bool:
    return secrets.compare_digest(username, configured_username) and secrets.compare_digest(
        password,
        configured_password,
    )


def create_platform_session_token(
    settings: Settings,
    *,
    username: str,
    role: str = ROLE_STUDENT,
    csrf_token: str | None = None,
    now: int | None = None,
) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"unsupported platform role: {role}")
    secret = _required_auth_secret(settings)
    issued_at = _now(now)
    expires_at = issued_at + _session_ttl(settings)
    payload = {
        "sub": username,
        "role": role,
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
    if role == PLATFORM_ROLE:
        # Tokens issued before roles existed map to the student experience.
        role = ROLE_STUDENT
    if role not in VALID_ROLES:
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
