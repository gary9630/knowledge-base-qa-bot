from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from fastapi import FastAPI, Request
from starlette.datastructures import URL, Headers

from app.audit import (
    AuditEventInput,
    fingerprint_secret,
    record_audit_event,
)
from app.models import AuditEvent


def test_audit_event_metadata_default_is_available_before_flush() -> None:
    event = AuditEvent(
        event_type="auth.login_succeeded",
        actor_type="platform",
        outcome="success",
    )

    assert event.metadata_json == {}


def test_fingerprint_secret_is_stable_and_does_not_return_the_secret() -> None:
    fingerprint = fingerprint_secret("super-secret-admin-key")

    assert fingerprint == fingerprint_secret("super-secret-admin-key")
    assert fingerprint != "super-secret-admin-key"
    assert len(fingerprint) == 16


def test_record_audit_event_uses_injected_recorder_with_request_context() -> None:
    events: list[AuditEventInput] = []
    app = FastAPI()
    app.state.audit_recorder = events.append
    request = cast(
        Request,
        SimpleNamespace(
            app=app,
            method="POST",
            url=URL("https://example.test/auth/login"),
            client=SimpleNamespace(host="203.0.113.10"),
            headers=Headers({"user-agent": "test-client"}),
            state=SimpleNamespace(request_id="req-123"),
        ),
    )

    record_audit_event(
        request,
        event_type="auth.login_failed",
        actor_type="platform",
        outcome="failure",
        actor_id="student",
        metadata={"reason": "invalid_credentials"},
    )

    assert events == [
        AuditEventInput(
            event_type="auth.login_failed",
            actor_type="platform",
            actor_id="student",
            outcome="failure",
            request_id="req-123",
            method="POST",
            path="/auth/login",
            client_host="203.0.113.10",
            user_agent="test-client",
            resource_type=None,
            resource_id=None,
            metadata={"reason": "invalid_credentials"},
        )
    ]
