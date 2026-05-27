from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app


def test_admin_audit_events_api_lists_security_events(
    db_session: Session,
    tmp_path: Path,
) -> None:
    client = TestClient(_audit_app(db_session, tmp_path))

    denied_response = client.get(
        "/evals/cases",
        headers={"X-KB-Admin-Key": "wrong-key", "X-Request-ID": "denied-admin"},
    )
    audit_response = client.get(
        "/admin/audit-events?event_type=admin.access_denied",
        headers={"X-KB-Admin-Key": "secret", "X-Request-ID": "audit-list"},
    )

    assert denied_response.status_code == 401
    assert audit_response.status_code == 200
    body = audit_response.json()
    assert body["events"][0]["event_type"] == "admin.access_denied"
    assert body["events"][0]["actor_type"] == "admin"
    assert body["events"][0]["outcome"] == "failure"
    assert body["events"][0]["request_id"] == "denied-admin"
    assert body["events"][0]["path"] == "/evals/cases"
    assert body["events"][0]["metadata"] == {"reason": "invalid_admin_key"}
    assert "wrong-key" not in str(body)
    assert "secret" not in str(body)


def _audit_app(db_session: Session, tmp_path: Path) -> FastAPI:
    settings = Settings(
        docs_dir=str(tmp_path / "docs"),
        raw_dir=str(tmp_path / "raw"),
        kb_dir=str(tmp_path / ".kb"),
        embedding_provider="fake",
        answer_provider="fake",
        admin_api_key="secret",
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
