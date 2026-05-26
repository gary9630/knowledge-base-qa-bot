from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.answer.providers import AnswerProvider, AnswerSource
from app.core.config import Settings
from app.main import create_app
from app.models.tables import EvalCase, EvalResult, EvalRun


@pytest.fixture
def app_with_indexed_docs(db_session: Session, tmp_path: Path) -> FastAPI:
    return _indexed_app(db_session, tmp_path)


def test_eval_case_create_list_run_and_latest_workflow(
    app_with_indexed_docs: FastAPI,
    db_session: Session,
) -> None:
    client = TestClient(app_with_indexed_docs)
    assert client.post("/index").status_code == 200

    create_response = client.post(
        "/evals/cases",
        json={
            "name": "course site",
            "query": "課程網站在哪？",
            "expected_decision": "can_answer",
            "expected_source_ids": ["常見問題FAQ.md#課程網站"],
            "tags": ["smoke", "citation"],
        },
    )
    assert create_response.status_code == 200
    case_body = create_response.json()
    case_id = UUID(case_body["id"])
    assert case_body["active"] is True

    cases_response = client.get("/evals/cases")
    assert cases_response.status_code == 200
    assert cases_response.json()["cases"][0]["id"] == str(case_id)

    run_response = client.post(
        "/evals/run",
        json={"case_ids": [str(case_id)], "strategy": "hybrid", "limit": 3},
    )

    assert run_response.status_code == 200
    run_body = run_response.json()
    assert run_body["status"] == "succeeded"
    assert run_body["stats"]["total"] == 1
    assert run_body["stats"]["passed"] == 1
    assert run_body["results"][0]["passed"] is True
    assert run_body["results"][0]["metrics"] == {
        "decision_match": 1.0,
        "retrieval_recall": 1.0,
        "citation_recall": 1.0,
    }

    latest_response = client.get("/evals/runs/latest")
    assert latest_response.status_code == 200
    assert latest_response.json()["id"] == run_body["id"]

    eval_case = db_session.get(EvalCase, case_id)
    eval_run = db_session.get(EvalRun, UUID(run_body["id"]))
    assert eval_case is not None
    assert eval_run is not None
    result = db_session.scalar(select(EvalResult).where(EvalResult.run_id == eval_run.id))
    assert result is not None
    assert result.passed is True


def test_eval_run_rejects_empty_or_unresolved_case_sets(
    app_with_indexed_docs: FastAPI,
) -> None:
    client = TestClient(app_with_indexed_docs)

    empty_response = client.post("/evals/run", json={"strategy": "hybrid", "limit": 3})
    missing_response = client.post(
        "/evals/run",
        json={"case_ids": [str(uuid4())], "strategy": "hybrid", "limit": 3},
    )

    assert empty_response.status_code == 409
    assert empty_response.json()["detail"] == "No active eval cases found."
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"].startswith("Eval cases not found or inactive:")


def test_eval_case_rejects_blank_name_and_query(
    app_with_indexed_docs: FastAPI,
) -> None:
    client = TestClient(app_with_indexed_docs)

    blank_name_response = client.post(
        "/evals/cases",
        json={
            "name": "   ",
            "query": "課程網站在哪？",
            "expected_decision": "can_answer",
        },
    )
    blank_query_response = client.post(
        "/evals/cases",
        json={
            "name": "course site",
            "query": "   ",
            "expected_decision": "can_answer",
        },
    )

    assert blank_name_response.status_code == 422
    assert blank_query_response.status_code == 422


def test_failed_eval_run_is_persisted_as_latest(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _indexed_app(
        db_session,
        tmp_path,
        answer_provider=FailingAnswerProvider(),
    )
    client = TestClient(app)
    assert client.post("/index").status_code == 200
    case_response = client.post(
        "/evals/cases",
        json={
            "name": "course site",
            "query": "課程網站在哪？",
            "expected_decision": "can_answer",
            "expected_source_ids": ["常見問題FAQ.md#課程網站"],
        },
    )
    assert case_response.status_code == 200

    run_response = client.post(
        "/evals/run",
        json={"case_ids": [case_response.json()["id"]], "strategy": "hybrid", "limit": 3},
    )

    assert run_response.status_code == 500
    assert run_response.json()["detail"] == "Eval run failed."

    latest_response = client.get("/evals/runs/latest")
    assert latest_response.status_code == 200
    latest_body = latest_response.json()
    assert latest_body["status"] == "failed"
    assert latest_body["error"] == "answer backend unavailable"
    assert latest_body["stats"] == {
        "total": 1,
        "passed": 0,
        "failed": 1,
        "pass_rate": 0.0,
        "average_score": 0.0,
    }
    assert latest_body["results"] == []

    eval_run = db_session.get(EvalRun, UUID(latest_body["id"]))
    assert eval_run is not None
    assert eval_run.status == "failed"
    assert eval_run.error == "answer backend unavailable"


def test_eval_endpoints_require_admin_key_when_configured(
    db_session: Session,
    tmp_path: Path,
) -> None:
    settings = Settings(
        docs_dir=str(tmp_path / "docs"),
        raw_dir=str(tmp_path / "raw"),
        kb_dir=str(tmp_path / ".kb"),
        embedding_provider="fake",
        answer_provider="fake",
        admin_api_key="secret",
    )
    app = create_app(settings=settings, session_factory=_session_factory(db_session))
    client = TestClient(app)

    response = client.get("/evals/cases")
    create_response = client.post(
        "/evals/cases",
        json={
            "name": "course site",
            "query": "課程網站在哪？",
            "expected_decision": "can_answer",
        },
    )
    run_response = client.post("/evals/run", json={"strategy": "hybrid", "limit": 3})
    latest_response = client.get("/evals/runs/latest")
    authed_response = client.get("/evals/cases", headers={"X-KB-Admin-Key": "secret"})

    assert response.status_code == 401
    assert create_response.status_code == 401
    assert run_response.status_code == 401
    assert latest_response.status_code == 401
    assert authed_response.status_code == 200


class FailingAnswerProvider:
    def generate_answer(
        self,
        query: str,
        sources: Sequence[AnswerSource],
        *,
        strict: bool = False,
    ) -> str:
        raise RuntimeError("answer backend unavailable")


def _indexed_app(
    db_session: Session,
    tmp_path: Path,
    *,
    answer_provider: AnswerProvider | None = None,
) -> FastAPI:
    docs_dir = tmp_path / "docs"
    raw_dir = tmp_path / "raw"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    (docs_dir / "常見問題FAQ.md").write_text(
        "# FAQ\n\n"
        "## 課程網站\n\n"
        "課程網站是 https://buildmoat.org/\n",
        encoding="utf-8",
    )
    settings = Settings(
        docs_dir=str(docs_dir),
        raw_dir=str(raw_dir),
        kb_dir=str(kb_dir),
        embedding_provider="fake",
        answer_provider="fake",
    )
    return create_app(
        settings=settings,
        session_factory=_session_factory(db_session),
        answer_provider=answer_provider,
    )


def _session_factory(db_session: Session) -> Callable[[], Session]:
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return create_session
