from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import (
    get_request_db_session,
    require_admin_access,
    require_platform_access,
)
from app.evals.cases import query_for_feedback
from app.models.tables import Feedback, Message

router = APIRouter()


class FeedbackRequest(BaseModel):
    message_id: UUID
    rating: int = Field(ge=-1, le=1)
    reason: str | None = None
    expected_source: str | None = None
    note: str | None = None


class FeedbackResponse(BaseModel):
    id: UUID
    message_id: UUID
    rating: int
    reason: str | None
    expected_source: str | None
    note: str | None


class FeedbackItemResponse(FeedbackResponse):
    query: str | None
    answer: str
    conversation_id: UUID


class FeedbackListResponse(BaseModel):
    feedback: list[FeedbackItemResponse]


@router.get(
    "/feedback",
    response_model=FeedbackListResponse,
    dependencies=[Depends(require_admin_access)],
)
def list_feedback(
    session: Annotated[Session, Depends(get_request_db_session)],
) -> FeedbackListResponse:
    feedback_items = session.scalars(
        select(Feedback)
        .options(selectinload(Feedback.message))
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
    ).all()
    return FeedbackListResponse(
        feedback=[feedback_item_response(session, item) for item in feedback_items]
    )


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    dependencies=[Depends(require_platform_access)],
)
def create_feedback(
    payload: FeedbackRequest,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> FeedbackResponse:
    message = session.get(Message, payload.message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    if message.role != "assistant":
        raise HTTPException(
            status_code=400,
            detail="Feedback can only be attached to assistant messages.",
        )

    feedback = Feedback(
        message_id=payload.message_id,
        rating=payload.rating,
        reason=payload.reason,
        expected_source=payload.expected_source,
        note=payload.note,
    )
    session.add(feedback)
    session.commit()
    return FeedbackResponse(
        id=feedback.id,
        message_id=feedback.message_id,
        rating=feedback.rating,
        reason=feedback.reason,
        expected_source=feedback.expected_source,
        note=feedback.note,
    )


def feedback_item_response(session: Session, feedback: Feedback) -> FeedbackItemResponse:
    try:
        query = query_for_feedback(session, feedback)
    except ValueError:
        query = None
    return FeedbackItemResponse(
        id=feedback.id,
        message_id=feedback.message_id,
        rating=feedback.rating,
        reason=feedback.reason,
        expected_source=feedback.expected_source,
        note=feedback.note,
        query=query,
        answer=feedback.message.content,
        conversation_id=feedback.message.conversation_id,
    )
