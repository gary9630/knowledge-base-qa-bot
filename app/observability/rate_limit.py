from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.audit import record_audit_event
from app.core.config import Settings
from app.observability.metrics import InMemoryMetrics

PLATFORM_SESSION_COOKIE = "kb_platform_session"
ADMIN_KEY_HEADER = "X-KB-Admin-Key"


class Clock(Protocol):
    def __call__(self) -> float: ...


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    policy: str
    limit: int
    remaining: int
    retry_after_seconds: int
    reset_after_seconds: int


@dataclass
class _Window:
    count: int
    reset_at: float


class InMemoryRateLimiter:
    def __init__(self, *, now: Clock = time.time) -> None:
        self._now = now
        self._lock = Lock()
        self._windows: dict[tuple[str, str], _Window] = {}

    def check(
        self,
        *,
        policy: str,
        identity: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitDecision(
                allowed=True,
                policy=policy,
                limit=limit,
                remaining=0,
                retry_after_seconds=0,
                reset_after_seconds=0,
            )

        now = self._now()
        key = (policy, identity)
        with self._lock:
            window = self._windows.get(key)
            if window is None or now >= window.reset_at:
                window = _Window(count=0, reset_at=now + window_seconds)
                self._windows[key] = window

            reset_after = _seconds_until(window.reset_at, now)
            if window.count >= limit:
                return RateLimitDecision(
                    allowed=False,
                    policy=policy,
                    limit=limit,
                    remaining=0,
                    retry_after_seconds=reset_after,
                    reset_after_seconds=reset_after,
                )

            window.count += 1
            remaining = max(0, limit - window.count)
            return RateLimitDecision(
                allowed=True,
                policy=policy,
                limit=limit,
                remaining=remaining,
                retry_after_seconds=reset_after,
                reset_after_seconds=reset_after,
            )


class UploadConcurrencyLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active_by_policy: dict[str, int] = {}

    def try_acquire(self, *, policy: str, limit: int) -> ConcurrencyGuard | None:
        if limit <= 0:
            return None

        with self._lock:
            active = self._active_by_policy.get(policy, 0)
            if active >= limit:
                return None
            self._active_by_policy[policy] = active + 1
        return ConcurrencyGuard(self, policy)

    def _release(self, policy: str) -> None:
        with self._lock:
            active = self._active_by_policy.get(policy, 0)
            if active <= 1:
                self._active_by_policy.pop(policy, None)
                return
            self._active_by_policy[policy] = active - 1


class ConcurrencyGuard:
    def __init__(self, limiter: UploadConcurrencyLimiter, policy: str) -> None:
        self._limiter = limiter
        self._policy = policy
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._limiter._release(self._policy)


@dataclass(frozen=True)
class _RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        settings = _settings_for_request(request)
        if not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        policy = _policy_for_request(request, settings)
        concurrency_guard = _acquire_upload_guard(request, settings, policy)
        if policy is not None and _is_upload_policy(policy) and concurrency_guard is None:
            _record_concurrency_limited(request, policy.name, settings)
            await _concurrency_limited_response()(scope, receive, send)
            return

        decision: RateLimitDecision | None = None
        if policy is not None:
            decision = _rate_limiter_for_request(request).check(
                policy=policy.name,
                identity=_identity_for_request(request, policy.name),
                limit=policy.limit,
                window_seconds=policy.window_seconds,
            )
            if not decision.allowed:
                _record_rate_limited(request, decision)
                if concurrency_guard is not None:
                    concurrency_guard.release()
                await _rate_limited_response(decision)(scope, receive, send)
                return

        async def send_with_rate_limit_headers(message: Message) -> None:
            if decision is not None and message["type"] == "http.response.start":
                message = _with_rate_limit_headers(message, decision)
            await send(message)

        try:
            await self.app(scope, receive, send_with_rate_limit_headers)
        finally:
            if concurrency_guard is not None:
                concurrency_guard.release()


def _policy_for_request(
    request: Request,
    settings: Settings,
) -> _RateLimitPolicy | None:
    method = request.method.upper()
    path = request.url.path
    window_seconds = settings.rate_limit_window_seconds

    if method == "POST" and path == "/auth/login":
        return _RateLimitPolicy("login", settings.rate_limit_login_requests, window_seconds)
    if method == "POST" and path in {"/chat", "/chat/stream"}:
        return _RateLimitPolicy("chat", settings.rate_limit_chat_requests, window_seconds)
    if method == "POST" and path == "/imports":
        return _RateLimitPolicy("upload", settings.rate_limit_upload_requests, window_seconds)
    if method in {"POST", "PUT", "PATCH", "DELETE"} and _is_admin_write_path(path):
        return _RateLimitPolicy("admin", settings.rate_limit_admin_requests, window_seconds)
    return None


def _is_admin_write_path(path: str) -> bool:
    return path == "/index" or path.startswith("/imports/") or path.startswith("/evals")


def _is_upload_policy(policy: _RateLimitPolicy) -> bool:
    return policy.name == "upload"


def _acquire_upload_guard(
    request: Request,
    settings: Settings,
    policy: _RateLimitPolicy | None,
) -> ConcurrencyGuard | None:
    if policy is None or not _is_upload_policy(policy):
        return None

    limiter = _upload_limiter_for_request(request)
    return limiter.try_acquire(policy=policy.name, limit=settings.max_concurrent_uploads)


def _rate_limiter_for_request(request: Request) -> InMemoryRateLimiter:
    limiter = getattr(request.app.state, "rate_limiter", None)
    if not isinstance(limiter, InMemoryRateLimiter):
        limiter = InMemoryRateLimiter()
        request.app.state.rate_limiter = limiter
    return limiter


def _upload_limiter_for_request(request: Request) -> UploadConcurrencyLimiter:
    limiter = getattr(request.app.state, "upload_concurrency_limiter", None)
    if not isinstance(limiter, UploadConcurrencyLimiter):
        limiter = UploadConcurrencyLimiter()
        request.app.state.upload_concurrency_limiter = limiter
    return limiter


def _settings_for_request(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings

    settings = Settings()
    request.app.state.settings = settings
    return settings


def _identity_for_request(request: Request, policy: str) -> str:
    parts = [_client_host(request)]
    if policy in {"chat", "upload", "admin"}:
        session_token = request.cookies.get(PLATFORM_SESSION_COOKIE)
        if session_token:
            parts.append(f"session:{_hash_identity(session_token)}")
    if policy in {"upload", "admin"}:
        admin_key = request.headers.get(ADMIN_KEY_HEADER)
        if admin_key:
            parts.append(f"admin:{_hash_identity(admin_key)}")
    return "|".join(parts)


def _client_host(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _hash_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _rate_limited_response(decision: RateLimitDecision) -> JSONResponse:
    return JSONResponse(
        {"detail": "Rate limit exceeded.", "policy": decision.policy},
        status_code=429,
        headers={
            "Retry-After": str(decision.retry_after_seconds),
            **_rate_limit_headers(decision),
        },
    )


def _concurrency_limited_response() -> JSONResponse:
    return JSONResponse(
        {"detail": "Too many concurrent upload requests.", "policy": "upload"},
        status_code=429,
        headers={"Retry-After": "1"},
    )


def _with_rate_limit_headers(
    message: Message,
    decision: RateLimitDecision,
) -> Message:
    existing_headers = [
        (name, value)
        for name, value in message.get("headers", [])
        if name.lower()
        not in {
            b"x-ratelimit-limit",
            b"x-ratelimit-remaining",
            b"x-ratelimit-reset",
        }
    ]
    headers = [
        *existing_headers,
        *[
            (name.encode("ascii"), value.encode("ascii"))
            for name, value in _rate_limit_headers(decision).items()
        ],
    ]
    return {**message, "headers": headers}


def _rate_limit_headers(decision: RateLimitDecision) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_after_seconds),
    }


def _record_rate_limited(request: Request, decision: RateLimitDecision) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics, InMemoryMetrics):
        metrics = InMemoryMetrics()
        request.app.state.metrics = metrics
    metrics.record_rate_limited(decision.policy)
    record_audit_event(
        request,
        event_type="security.rate_limited",
        actor_type="client",
        actor_id=_client_host(request),
        outcome="blocked",
        metadata={
            "policy": decision.policy,
            "limit": decision.limit,
            "retry_after_seconds": decision.retry_after_seconds,
            "reset_after_seconds": decision.reset_after_seconds,
        },
    )


def _record_concurrency_limited(
    request: Request,
    policy: str,
    settings: Settings,
) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics, InMemoryMetrics):
        metrics = InMemoryMetrics()
        request.app.state.metrics = metrics
    metrics.record_concurrency_limited(policy)
    record_audit_event(
        request,
        event_type="security.upload_concurrency_limited",
        actor_type="client",
        actor_id=_client_host(request),
        outcome="blocked",
        metadata={
            "policy": policy,
            "max_concurrent_uploads": settings.max_concurrent_uploads,
        },
    )


def _seconds_until(reset_at: float, now: float) -> int:
    return max(1, math.ceil(reset_at - now))
