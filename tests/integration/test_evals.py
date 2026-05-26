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
from app.models.tables import (
    Conversation,
    EvalCase,
    EvalResult,
    EvalRun,
    Feedback,
    Message,
    RetrievalEvent,
)
from app.retrieval.embeddings import FakeEmbeddingProvider
from scripts.run_evals import main as run_evals_main


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


def test_eval_seed_endpoint_upserts_cases_by_seed_key(
    app_with_indexed_docs: FastAPI,
    db_session: Session,
) -> None:
    client = TestClient(app_with_indexed_docs)
    payload = {
        "cases": [
            {
                "seed_key": "faq.course-site",
                "name": "FAQ course site",
                "query": "課程網站在哪？",
                "expected_decision": "can_answer",
                "expected_source_ids": ["常見問題FAQ.md#課程網站"],
                "tags": ["seed", "faq"],
                "metadata": {"fixture": "default"},
            }
        ]
    }

    first_response = client.post("/evals/seed", json=payload)
    second_response = client.post(
        "/evals/seed",
        json={
            "cases": [
                {
                    **payload["cases"][0],
                    "name": "FAQ course site updated",
                    "tags": ["seed", "faq", "updated"],
                }
            ]
        },
    )

    assert first_response.status_code == 200
    assert first_response.json()["summary"] == {"created": 1, "updated": 0, "total": 1}
    assert second_response.status_code == 200
    assert second_response.json()["summary"] == {"created": 0, "updated": 1, "total": 1}

    cases = db_session.scalars(select(EvalCase).where(EvalCase.seed_key == "faq.course-site")).all()
    assert len(cases) == 1
    assert cases[0].name == "FAQ course site updated"
    assert cases[0].source_kind == "seed"
    assert cases[0].tags_json == ["seed", "faq", "updated"]


def test_feedback_can_be_promoted_to_eval_case_idempotently(
    db_session: Session,
    tmp_path: Path,
) -> None:
    app = _indexed_app(db_session, tmp_path)
    client = TestClient(app)
    feedback = _feedback_for_query(db_session, query="課程網站在哪？")

    list_response = client.get("/feedback")
    first_response = client.post(
        "/evals/cases/promote-feedback",
        json={"feedback_id": str(feedback.id), "tags": ["regression", "feedback"]},
    )
    second_response = client.post(
        "/evals/cases/promote-feedback",
        json={"feedback_id": str(feedback.id), "tags": ["regression", "feedback"]},
    )

    assert list_response.status_code == 200
    assert list_response.json()["feedback"][0]["query"] == "課程網站在哪？"
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_body = first_response.json()
    second_body = second_response.json()
    assert first_body["id"] == second_body["id"]
    assert first_body["query"] == "課程網站在哪？"
    assert first_body["expected_decision"] == "can_answer"
    assert first_body["expected_source_ids"] == ["常見問題FAQ.md#課程網站"]
    assert first_body["source_kind"] == "feedback"
    assert first_body["promoted_feedback_id"] == str(feedback.id)

    promoted_case = db_session.get(EvalCase, UUID(first_body["id"]))
    assert promoted_case is not None
    assert promoted_case.promoted_feedback_id == feedback.id
    assert promoted_case.metadata_json["feedback_id"] == str(feedback.id)
    assert promoted_case.metadata_json["rating"] == -1


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


def test_cli_eval_runner_persists_scheduled_trigger(
    app_with_indexed_docs: FastAPI,
    db_session: Session,
) -> None:
    client = TestClient(app_with_indexed_docs)
    assert client.post("/index").status_code == 200
    seed_response = client.post(
        "/evals/seed",
        json={
            "cases": [
                {
                    "seed_key": "faq.course-site",
                    "name": "FAQ course site",
                    "query": "課程網站在哪？",
                    "expected_decision": "can_answer",
                    "expected_source_ids": ["常見問題FAQ.md#課程網站"],
                }
            ]
        },
    )
    assert seed_response.status_code == 200

    exit_code = run_evals_main(
        ["--trigger", "scheduled", "--limit", "3"],
        session_factory=_session_factory(db_session),
        embedding_provider=FakeEmbeddingProvider(),
        answer_provider=app_with_indexed_docs.state.answer_provider,
    )

    eval_run = db_session.scalar(select(EvalRun).order_by(EvalRun.created_at.desc()))
    assert exit_code == 0
    assert eval_run is not None
    assert eval_run.trigger == "scheduled"
    assert eval_run.status == "succeeded"


def test_eval_report_summarizes_latest_failures(
    app_with_indexed_docs: FastAPI,
) -> None:
    client = TestClient(app_with_indexed_docs)
    assert client.post("/index").status_code == 200
    case_response = client.post(
        "/evals/cases",
        json={
            "name": "wrong source expectation",
            "query": "課程網站在哪？",
            "expected_decision": "can_answer",
            "expected_source_ids": ["missing.md#source"],
            "tags": ["report"],
        },
    )
    assert case_response.status_code == 200
    run_response = client.post(
        "/evals/run",
        json={"case_ids": [case_response.json()["id"]], "strategy": "hybrid", "limit": 3},
    )
    assert run_response.status_code == 200

    report_response = client.get("/evals/report")

    assert report_response.status_code == 200
    report = report_response.json()
    assert report["totals"]["total_cases"] == 1
    assert report["totals"]["active_cases"] == 1
    assert report["totals"]["total_runs"] == 1
    assert report["latest_run"]["id"] == run_response.json()["id"]
    assert report["latest_run"]["stats"]["failed"] == 1
    assert report["recent_runs"][0]["id"] == run_response.json()["id"]
    assert report["latest_failures"][0]["case_id"] == case_response.json()["id"]
    assert report["latest_failures"][0]["missing_source_ids"] == ["missing.md#source"]
    assert report["worst_cases"][0]["case_id"] == case_response.json()["id"]
    assert report["worst_cases"][0]["failed"] == 1


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
    feedback_response = client.get("/feedback")
    create_response = client.post(
        "/evals/cases",
        json={
            "name": "course site",
            "query": "課程網站在哪？",
            "expected_decision": "can_answer",
        },
    )
    seed_response = client.post("/evals/seed", json={})
    promote_response = client.post(
        "/evals/cases/promote-feedback",
        json={"feedback_id": str(uuid4())},
    )
    run_response = client.post("/evals/run", json={"strategy": "hybrid", "limit": 3})
    latest_response = client.get("/evals/runs/latest")
    report_response = client.get("/evals/report")
    authed_response = client.get("/evals/cases", headers={"X-KB-Admin-Key": "secret"})

    assert response.status_code == 401
    assert feedback_response.status_code == 401
    assert create_response.status_code == 401
    assert seed_response.status_code == 401
    assert promote_response.status_code == 401
    assert run_response.status_code == 401
    assert latest_response.status_code == 401
    assert report_response.status_code == 401
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


def _feedback_for_query(db_session: Session, *, query: str) -> Feedback:
    conversation_id = uuid4()
    assistant_message_id = uuid4()
    conversation = Conversation(id=conversation_id, title=query)
    user_message = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        role="user",
        content=query,
    )
    assistant_message = Message(
        id=assistant_message_id,
        conversation_id=conversation_id,
        role="assistant",
        content="我無法從知識庫確認這件事。",
        sources_json=[],
    )
    db_session.add_all([conversation, user_message, assistant_message])
    db_session.flush()

    retrieval_event = RetrievalEvent(
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        query=query,
        strategy="hybrid",
        selected_sources_json=[],
        scores_json={},
        decision="cannot_confirm",
    )
    feedback = Feedback(
        message_id=assistant_message_id,
        rating=-1,
        reason="missing_source",
        expected_source="常見問題FAQ.md#課程網站",
        note="Should cite the FAQ.",
    )
    db_session.add_all([retrieval_event, feedback])
    db_session.commit()
    return feedback


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
