from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models.tables import AuditEvent


def test_platform_login_session_and_logout_workflow(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_auth_app(db_session, tmp_path))

    login_response = client.post(
        "/auth/login",
        json={"username": "student", "password": "pass"},
    )
    session_response = client.get("/auth/session")
    logout_response = client.post("/auth/logout")
    logged_out_response = client.get("/auth/session")

    assert login_response.status_code == 200
    login_body = login_response.json()
    assert login_body["authenticated"] is True
    assert login_body["username"] == "student"
    assert login_body["csrf_token"]
    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True
    assert session_response.json()["csrf_token"] == login_body["csrf_token"]
    assert logout_response.status_code == 200
    assert logged_out_response.status_code == 200
    assert logged_out_response.json()["authenticated"] is False


def test_configured_platform_auth_protects_product_apis_and_requires_csrf(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_auth_app(db_session, tmp_path))

    unauthenticated_sources = client.get("/sources")
    unauthenticated_chat = client.post("/chat", json={"query": "課程網站在哪？"})
    login_response = client.post(
        "/auth/login",
        json={"username": "student", "password": "pass"},
    )
    csrf_token = login_response.json()["csrf_token"]
    missing_csrf_chat = client.post("/chat", json={"query": "課程網站在哪？"})
    authed_chat = client.post(
        "/chat",
        headers={"X-KB-CSRF-Token": csrf_token},
        json={"query": "課程網站在哪？"},
    )

    assert unauthenticated_sources.status_code == 401
    assert unauthenticated_chat.status_code == 401
    assert missing_csrf_chat.status_code == 403
    assert authed_chat.status_code == 200
    assert authed_chat.json()["answer"] == "知識庫尚未建立索引，請先建立索引。"


def test_development_product_apis_remain_open_when_platform_auth_is_unconfigured(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_auth_app(db_session, tmp_path, platform_auth=False))

    response = client.post("/chat", json={"query": "課程網站在哪？"})

    assert response.status_code == 200


def test_production_product_apis_fail_closed_when_platform_auth_is_unconfigured(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(
        _auth_app(db_session, tmp_path, platform_auth=False, app_env="production")
    )

    response = client.get("/sources")

    assert response.status_code == 503
    assert response.json()["detail"] == "Platform auth is required but not configured."


def test_admin_api_key_still_authorizes_admin_routes_without_platform_session(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_auth_app(db_session, tmp_path, admin_api_key="secret"))

    response = client.get("/evals/cases", headers={"X-KB-Admin-Key": "secret"})

    assert response.status_code == 200


def test_platform_login_uses_generic_error_for_invalid_credentials(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_auth_app(db_session, tmp_path))

    response = client.post(
        "/auth/login",
        json={"username": "student", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_platform_auth_writes_audit_events(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_auth_app(db_session, tmp_path))

    failed_response = client.post(
        "/auth/login",
        json={"username": "student", "password": "wrong"},
        headers={"X-Request-ID": "login-failed-request"},
    )
    login_response = client.post(
        "/auth/login",
        json={"username": "student", "password": "pass"},
        headers={"X-Request-ID": "login-success-request"},
    )
    logout_response = client.post(
        "/auth/logout",
        headers={"X-Request-ID": "logout-request"},
    )

    events = db_session.scalars(
        select(AuditEvent).order_by(AuditEvent.created_at.asc(), AuditEvent.event_type.asc())
    ).all()
    event_map = {event.event_type: event for event in events}

    assert failed_response.status_code == 401
    assert login_response.status_code == 200
    assert logout_response.status_code == 200
    assert set(event_map) == {
        "auth.login_failed",
        "auth.login_succeeded",
        "auth.logout",
    }
    assert event_map["auth.login_failed"].actor_type == "platform"
    assert event_map["auth.login_failed"].actor_id == "student"
    assert event_map["auth.login_failed"].outcome == "failure"
    assert event_map["auth.login_failed"].request_id == "login-failed-request"
    assert event_map["auth.login_failed"].metadata_json == {
        "reason": "invalid_credentials"
    }
    assert event_map["auth.login_succeeded"].actor_id == "student"
    assert event_map["auth.login_succeeded"].outcome == "success"
    assert event_map["auth.logout"].actor_id == "student"
    assert all("password" not in event.metadata_json for event in events)


def _auth_app(
    db_session: Session,
    tmp_path: Path,
    *,
    platform_auth: bool = True,
    admin_api_key: str | None = None,
    app_env: str = "development",
) -> FastAPI:
    settings = Settings(
        app_env=app_env,
        docs_dir=str(tmp_path / "docs"),
        raw_dir=str(tmp_path / "raw"),
        kb_dir=str(tmp_path / ".kb"),
        embedding_provider="fake",
        answer_provider="fake",
        admin_api_key=admin_api_key,
        auth_secret_key="test-secret" if platform_auth else None,
        platform_username="student" if platform_auth else None,
        platform_password="pass" if platform_auth else None,
    )
    return create_app(settings=settings, session_factory=_session_factory(db_session))


def _session_factory(db_session: Session) -> Callable[[], Session]:
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return create_session
