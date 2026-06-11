from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.retrieval.dimensions import PGVECTOR_EMBEDDING_DIMENSION


def default_visibility() -> list[str]:
    return ["public"]


class JsonDefaultsMixin:
    __json_defaults__: ClassVar[dict[str, Callable[[], object]]] = {}
    __scalar_defaults__: ClassVar[dict[str, object]] = {}

    def __init__(self, **kwargs: Any) -> None:
        for key, value in self.__scalar_defaults__.items():
            kwargs.setdefault(key, value)
        for key, factory in self.__json_defaults__.items():
            kwargs.setdefault(key, factory())

        super().__init__(**kwargs)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Document(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_filename", "filename"),
        Index("ix_documents_source_type", "source_type"),
        Index("ix_documents_lifecycle_status", "lifecycle_status"),
        Index("ix_documents_visibility", "visibility", postgresql_using="gin"),
    )
    __json_defaults__ = {
        "visibility": default_visibility,
        "metadata_json": dict,
    }
    __scalar_defaults__ = {"lifecycle_status": "active"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    lifecycle_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    lifecycle_reason: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=default_visibility,
        server_default=text("""'["public"]'::jsonb"""),
    )
    imported_from: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    sections: Mapped[list[Section]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class Section(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "sections"
    __table_args__ = (
        Index("ux_sections_source_id", "source_id", unique=True),
        Index("ix_sections_tsv", "tsv", postgresql_using="gin"),
        # intentionally non-unique — reindex renumbers positions in-place with
        # per-row flushes, so a unique constraint would violate mid-transaction
        # during reorders.
        Index("ix_sections_document_position", "document_id", "position"),
    )
    __json_defaults__ = {"metadata_json": dict}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str] = mapped_column(Text, nullable=False)
    heading_slug: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    document: Mapped[Document] = relationship(back_populates="sections")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )


class Chunk(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ux_chunks_section_id_chunk_index", "section_id", "chunk_index", unique=True),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    __json_defaults__ = {"metadata_json": dict}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    section_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(PGVECTOR_EMBEDDING_DIMENSION))
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    section: Mapped[Section] = relationship(back_populates="chunks")


class IndexingJob(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "indexing_jobs"
    __table_args__ = (Index("ix_indexing_jobs_status_created_at", "status", "created_at"),)
    __json_defaults__ = {"stats_json": dict}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    input_path: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    stats_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class IngestionJob(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_kind_status", "kind", "status"),
        Index("ix_ingestion_jobs_status_created_at", "status", "created_at"),
    )
    __json_defaults__ = {"metadata_json": dict}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_path: Mapped[str | None] = mapped_column(Text)
    canonical_path: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str | None] = mapped_column(Text, index=True)
    title: Mapped[str | None] = mapped_column(Text)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class Message(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __json_defaults__ = {"sources_json": list}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    feedback_items: Mapped[list[Feedback]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


class RetrievalEvent(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "retrieval_events"
    __json_defaults__ = {
        "selected_sources_json": list,
        "scores_json": dict,
    }

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        index=True,
    )
    message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    selected_sources_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    scores_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class AuditEvent(JsonDefaultsMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_event_type_created_at", "event_type", "created_at"),
        Index("ix_audit_events_actor", "actor_type", "actor_id"),
        Index("ix_audit_events_outcome_created_at", "outcome", "created_at"),
        Index("ix_audit_events_request_id", "request_id"),
    )
    __json_defaults__ = {"metadata_json": dict}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(Text)
    client_host: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class BackgroundJob(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_status_available_at", "status", "available_at"),
        Index("ix_background_jobs_task_type_created_at", "task_type", "created_at"),
        Index("ix_background_jobs_locked_at", "locked_at"),
    )
    __json_defaults__ = {
        "payload_json": dict,
        "result_json": dict,
    }
    __scalar_defaults__ = {
        "status": "queued",
        "priority": 100,
        "attempts": 0,
        "max_attempts": 3,
    }

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="queued",
        server_default=text("'queued'"),
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default=text("100"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default=text("3"),
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        "payload",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(
        "result",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackgroundWorkerHeartbeat(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "background_worker_heartbeats"
    __table_args__ = (
        Index("ix_background_worker_heartbeats_last_seen_at", "last_seen_at"),
    )
    __scalar_defaults__ = {
        "status": "starting",
        "processed_jobs": 0,
    }

    worker_id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="starting",
        server_default=text("'starting'"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_jobs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    current_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    current_task_type: Mapped[str | None] = mapped_column(Text)
    last_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    last_task_type: Mapped[str | None] = mapped_column(Text)
    last_job_status: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    expected_source: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    message: Mapped[Message] = relationship(back_populates="feedback_items")


class EvalCase(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "eval_cases"
    __table_args__ = (
        Index("ix_eval_cases_active", "active"),
        Index("ix_eval_cases_created_at", "created_at"),
        Index("ix_eval_cases_source_kind", "source_kind"),
        Index("ux_eval_cases_seed_key", "seed_key", unique=True),
        Index("ux_eval_cases_promoted_feedback_id", "promoted_feedback_id", unique=True),
    )
    __json_defaults__ = {
        "expected_sources_json": list,
        "tags_json": list,
        "metadata_json": dict,
    }
    __scalar_defaults__ = {"source_kind": "manual"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_decision: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
    )
    seed_key: Mapped[str | None] = mapped_column(Text)
    promoted_feedback_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("feedback.id", ondelete="SET NULL"),
    )
    expected_sources_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    tags_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    results: Mapped[list[EvalResult]] = relationship(back_populates="case")


class EvalRun(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("ix_eval_runs_status_created_at", "status", "created_at"),
        Index("ix_eval_runs_trigger_created_at", "trigger", "created_at"),
    )
    __json_defaults__ = {"stats_json": dict}
    __scalar_defaults__ = {"trigger": "manual"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    limit: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
    )
    error: Mapped[str | None] = mapped_column(Text)
    stats_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    results: Mapped[list[EvalResult]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EvalResult(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        Index("ix_eval_results_run_id", "run_id"),
        Index("ix_eval_results_case_id", "case_id"),
        Index("ix_eval_results_passed", "passed"),
    )
    __json_defaults__ = {
        "expected_sources_json": list,
        "selected_sources_json": list,
        "cited_sources_json": list,
        "missing_sources_json": list,
        "unexpected_sources_json": list,
        "metrics_json": dict,
    }

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_decision: Mapped[str] = mapped_column(Text, nullable=False)
    actual_decision: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    expected_sources_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    selected_sources_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    cited_sources_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    missing_sources_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    unexpected_sources_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    run: Mapped[EvalRun] = relationship(back_populates="results")
    case: Mapped[EvalCase] = relationship(back_populates="results")


class ConceptCluster(TimestampMixin, Base):
    __tablename__ = "concept_clusters"
    __table_args__ = (Index("ux_concept_clusters_name", "name", unique=True),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    concepts: Mapped[list[Concept]] = relationship(back_populates="cluster")


class Concept(JsonDefaultsMixin, TimestampMixin, Base):
    __tablename__ = "concepts"
    __table_args__ = (Index("ux_concepts_slug", "slug", unique=True),)
    __json_defaults__ = {"aliases": list}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    cluster_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("concept_clusters.id", ondelete="SET NULL"),
    )
    aliases: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    cluster: Mapped[ConceptCluster | None] = relationship(back_populates="concepts")
    sources: Mapped[list[ConceptSource]] = relationship(
        back_populates="concept",
        cascade="all, delete-orphan",
    )


class ConceptEdge(TimestampMixin, Base):
    __tablename__ = "concept_edges"
    __table_args__ = (
        Index(
            "ux_concept_edges_source_target_kind",
            "source_concept_id",
            "target_concept_id",
            "kind",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_concept_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_concept_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)


class ConceptSource(TimestampMixin, Base):
    __tablename__ = "concept_sources"
    __table_args__ = (
        Index("ux_concept_sources_concept_section", "concept_id", "section_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    concept_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    concept: Mapped[Concept] = relationship(back_populates="sources")
    section: Mapped[Section] = relationship()


class ConceptExtractionState(TimestampMixin, Base):
    __tablename__ = "concept_extraction_state"
    __table_args__ = (Index("ux_concept_extraction_state_document", "document_id", unique=True),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
