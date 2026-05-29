from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.audit import AuditEventInput
from app.core.config import Settings
from app.observability.metrics import InMemoryMetrics
from app.observability.rate_limit import (
    InMemoryRateLimiter,
    RateLimitMiddleware,
    UploadConcurrencyLimiter,
)


def test_fixed_window_limiter_blocks_after_limit_until_window_resets() -> None:
    now = _mutable_clock(100.0)
    limiter = InMemoryRateLimiter(now=now)

    first = limiter.check(
        policy="login",
        identity="client-1",
        limit=2,
        window_seconds=60,
    )
    second = limiter.check(
        policy="login",
        identity="client-1",
        limit=2,
        window_seconds=60,
    )
    blocked = limiter.check(
        policy="login",
        identity="client-1",
        limit=2,
        window_seconds=60,
    )
    now.set(161.0)
    reset = limiter.check(
        policy="login",
        identity="client-1",
        limit=2,
        window_seconds=60,
    )

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 60
    assert reset.allowed is True
    assert reset.remaining == 1


def test_rate_limit_middleware_returns_429_with_headers_and_metrics() -> None:
    client, app = _client(
        Settings(
            rate_limit_login_requests=2,
            rate_limit_window_seconds=60,
        )
    )
    audit_events: list[AuditEventInput] = []
    app.state.audit_recorder = audit_events.append

    first = client.post("/auth/login", json={"username": "student", "password": "bad"})
    second = client.post("/auth/login", json={"username": "student", "password": "bad"})
    blocked = client.post("/auth/login", json={"username": "student", "password": "bad"})

    metrics = app.state.metrics.snapshot()

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.status_code == 200
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Rate limit exceeded."
    assert blocked.json()["policy"] == "login"
    assert blocked.headers["Retry-After"] == "60"
    assert blocked.headers["X-RateLimit-Limit"] == "2"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert metrics["rate_limited_total"] == 1
    assert metrics["rate_limited_by_policy"] == {"login": 1}
    assert audit_events == [
        AuditEventInput(
            event_type="security.rate_limited",
            actor_type="client",
            actor_id="testclient",
            outcome="blocked",
            request_id=None,
            method="POST",
            path="/auth/login",
            client_host="testclient",
            user_agent="testclient",
            resource_type=None,
            resource_id=None,
            metadata={
                "policy": "login",
                "limit": 2,
                "retry_after_seconds": 60,
                "reset_after_seconds": 60,
            },
        )
    ]


def test_rate_limit_middleware_can_be_disabled() -> None:
    client, app = _client(
        Settings(
            rate_limit_enabled=False,
            rate_limit_login_requests=1,
        )
    )

    first = client.post("/auth/login", json={"username": "student", "password": "bad"})
    second = client.post("/auth/login", json={"username": "student", "password": "bad"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert app.state.metrics.snapshot()["rate_limited_total"] == 0


def test_upload_concurrency_limiter_rejects_when_limit_is_already_active() -> None:
    limiter = UploadConcurrencyLimiter()
    first_guard = limiter.try_acquire(policy="upload", limit=1)
    second_guard = limiter.try_acquire(policy="upload", limit=1)

    assert first_guard is not None
    assert second_guard is None

    first_guard.release()
    third_guard = limiter.try_acquire(policy="upload", limit=1)

    assert third_guard is not None
    third_guard.release()


def test_upload_concurrency_middleware_rejects_before_route_runs() -> None:
    app = FastAPI()
    app.state.settings = Settings(
        max_concurrent_uploads=1,
        rate_limit_upload_requests=100,
    )
    app.state.metrics = InMemoryMetrics()
    audit_events: list[AuditEventInput] = []
    app.state.audit_recorder = audit_events.append
    app.state.upload_concurrency_limiter = UploadConcurrencyLimiter()
    active_guard = app.state.upload_concurrency_limiter.try_acquire(
        policy="upload",
        limit=1,
    )
    route_calls = 0
    app.add_middleware(RateLimitMiddleware)

    @app.post("/imports")
    async def upload() -> dict[str, str]:
        nonlocal route_calls
        route_calls += 1
        return {"status": "ok"}

    try:
        response = TestClient(app).post(
            "/imports",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    finally:
        assert active_guard is not None
        active_guard.release()

    metrics = app.state.metrics.snapshot()

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many concurrent upload requests."
    assert response.headers["Retry-After"] == "1"
    assert route_calls == 0
    assert metrics["concurrency_limited_total"] == 1
    assert metrics["concurrency_limited_by_policy"] == {"upload": 1}
    assert audit_events == [
        AuditEventInput(
            event_type="security.upload_concurrency_limited",
            actor_type="client",
            actor_id="testclient",
            outcome="blocked",
            request_id=None,
            method="POST",
            path="/imports",
            client_host="testclient",
            user_agent="testclient",
            resource_type=None,
            resource_id=None,
            metadata={
                "policy": "upload",
                "max_concurrent_uploads": 1,
            },
        )
    ]


def _client(settings: Settings) -> tuple[TestClient, FastAPI]:
    app = FastAPI()
    app.state.settings = settings
    app.state.metrics = InMemoryMetrics()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/auth/login")
    def login() -> dict[str, str]:
        return {"status": "checked"}

    return TestClient(app), app


class _MutableClock:
    def __init__(self, value: float) -> None:
        self._value = value

    def __call__(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        self._value = value


def _mutable_clock(initial: float) -> _MutableClock:
    return _MutableClock(initial)
