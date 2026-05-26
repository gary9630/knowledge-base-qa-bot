from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import EvalCase, Feedback, Message, RetrievalEvent
from app.retrieval.models import RetrievalDecision

EvalCaseSourceKind = Literal["manual", "seed", "feedback"]


@dataclass(frozen=True)
class EvalSeedCase:
    seed_key: str
    name: str
    query: str
    expected_decision: RetrievalDecision
    expected_source_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    active: bool = True


@dataclass(frozen=True)
class EvalSeedSummary:
    created: int
    updated: int
    total: int


def load_default_seed_cases(path: Path | None = None) -> list[EvalSeedCase]:
    seed_path = path or Path(__file__).with_name("default_seed_cases.json")
    raw_cases = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise ValueError("eval seed file must contain a list of cases")
    return parse_seed_cases(raw_cases)


def parse_seed_cases(raw_cases: list[dict[str, Any]]) -> list[EvalSeedCase]:
    seen_seed_keys: set[str] = set()
    cases: list[EvalSeedCase] = []
    for raw_case in raw_cases:
        seed_key = _required_text(raw_case, "seed_key")
        if seed_key in seen_seed_keys:
            raise ValueError(f"duplicate seed_key: {seed_key}")
        seen_seed_keys.add(seed_key)
        cases.append(
            EvalSeedCase(
                seed_key=seed_key,
                name=_required_text(raw_case, "name"),
                query=_required_text(raw_case, "query"),
                expected_decision=_expected_decision(raw_case),
                expected_source_ids=tuple(_unique_strings(raw_case.get("expected_source_ids"))),
                tags=tuple(_unique_strings(raw_case.get("tags"))),
                metadata=_metadata(raw_case.get("metadata")),
                active=_active(raw_case.get("active")),
            )
        )
    return cases


def seed_eval_cases(
    session: Session,
    cases: list[EvalSeedCase],
) -> tuple[EvalSeedSummary, list[EvalCase]]:
    created = 0
    updated = 0
    eval_cases: list[EvalCase] = []
    for seed_case in cases:
        eval_case = session.scalar(
            select(EvalCase).where(EvalCase.seed_key == seed_case.seed_key)
        )
        if eval_case is None:
            eval_case = EvalCase(seed_key=seed_case.seed_key)
            session.add(eval_case)
            created += 1
        else:
            updated += 1

        eval_case.source_kind = "seed"
        eval_case.name = seed_case.name
        eval_case.query = seed_case.query
        eval_case.expected_decision = seed_case.expected_decision
        eval_case.expected_sources_json = list(seed_case.expected_source_ids)
        eval_case.tags_json = list(seed_case.tags)
        eval_case.metadata_json = dict(seed_case.metadata)
        eval_case.active = seed_case.active
        eval_cases.append(eval_case)

    return EvalSeedSummary(created=created, updated=updated, total=len(cases)), eval_cases


def promote_feedback_to_eval_case(
    session: Session,
    *,
    feedback_id: UUID,
    expected_decision: RetrievalDecision | None = None,
    expected_source_ids: list[str] | None = None,
    tags: list[str] | None = None,
    active: bool = True,
) -> EvalCase:
    feedback = session.get(Feedback, feedback_id)
    if feedback is None:
        raise ValueError("Feedback not found.")
    if feedback.message.role != "assistant":
        raise ValueError("Feedback can only be promoted from assistant messages.")

    query = query_for_feedback(session, feedback)
    source_ids = _promotion_sources(feedback, expected_source_ids)
    decision = expected_decision or ("can_answer" if source_ids else "cannot_confirm")
    eval_case = session.scalar(
        select(EvalCase).where(EvalCase.promoted_feedback_id == feedback.id)
    )
    if eval_case is None:
        eval_case = EvalCase(promoted_feedback_id=feedback.id)
        session.add(eval_case)

    eval_case.source_kind = "feedback"
    eval_case.name = f"Feedback regression: {query[:80]}"
    eval_case.query = query
    eval_case.expected_decision = decision
    eval_case.expected_sources_json = source_ids
    eval_case.tags_json = _unique_values([*(tags or []), "feedback"])
    eval_case.metadata_json = {
        "feedback_id": str(feedback.id),
        "assistant_message_id": str(feedback.message_id),
        "conversation_id": str(feedback.message.conversation_id),
        "rating": feedback.rating,
        "reason": feedback.reason,
        "note": feedback.note,
    }
    eval_case.active = active
    return eval_case


def query_for_feedback(session: Session, feedback: Feedback) -> str:
    retrieval_event = session.scalar(
        select(RetrievalEvent)
        .where(RetrievalEvent.message_id == feedback.message_id)
        .order_by(RetrievalEvent.created_at.desc(), RetrievalEvent.id.desc())
        .limit(1)
    )
    if retrieval_event is not None:
        return retrieval_event.query

    assistant_message = feedback.message
    user_message = session.scalar(
        select(Message)
        .where(
            Message.conversation_id == assistant_message.conversation_id,
            Message.role == "user",
            Message.created_at <= assistant_message.created_at,
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )
    if user_message is None:
        raise ValueError("Feedback message has no preceding user query.")
    return user_message.content


def _promotion_sources(
    feedback: Feedback,
    expected_source_ids: list[str] | None,
) -> list[str]:
    provided_sources = _unique_values(expected_source_ids or [])
    if provided_sources:
        return provided_sources
    return _unique_values([feedback.expected_source] if feedback.expected_source else [])


def _required_text(raw_case: dict[str, Any], key: str) -> str:
    value = raw_case.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"seed case requires non-empty {key}")
    return value.strip()


def _expected_decision(raw_case: dict[str, Any]) -> RetrievalDecision:
    value = raw_case.get("expected_decision")
    if value not in {"can_answer", "cannot_confirm"}:
        raise ValueError("expected_decision must be can_answer or cannot_confirm")
    return cast(RetrievalDecision, value)


def _unique_strings(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected list of strings")
    seen: set[str] = set()
    values: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("expected list of strings")
        stripped = item.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        values.append(stripped)
    return values


def _unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        unique.append(stripped)
    return unique


def _metadata(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    return dict(value)


def _active(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, bool):
        raise ValueError("active must be a boolean")
    return value
