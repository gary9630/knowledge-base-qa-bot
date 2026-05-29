from uuid import uuid4

from app.models import (
    BackgroundJob,
    Chunk,
    Document,
    EvalCase,
    EvalResult,
    EvalRun,
    IndexingJob,
    Message,
    RetrievalEvent,
    Section,
)


def test_json_defaults_are_available_before_flush() -> None:
    document = Document(
        filename="faq.md",
        canonical_path="docs/faq.md",
        source_type="md",
        content_hash="document-hash",
    )
    section = Section(
        document_id=uuid4(),
        source_id="faq.md#intro",
        heading="Intro",
        heading_slug="intro",
        level=1,
        body_md="Body",
        content_hash="section-hash",
    )
    chunk = Chunk(
        section_id=uuid4(),
        chunk_index=0,
        body_text="Body",
        content_hash="chunk-hash",
    )
    background_job = BackgroundJob(task_type="index.rebuild")
    indexing_job = IndexingJob(kind="index", status="pending")
    message = Message(conversation_id=uuid4(), role="assistant", content="Answer")
    retrieval_event = RetrievalEvent(
        query="Question",
        strategy="hybrid",
        decision="answered",
    )
    feedback_id = uuid4()
    eval_case = EvalCase(
        name="Case",
        query="Question",
        expected_decision="can_answer",
        seed_key="seed.case",
        promoted_feedback_id=feedback_id,
    )
    eval_run = EvalRun(status="running", strategy="hybrid", limit=5)
    eval_result = EvalResult(
        run_id=uuid4(),
        case_id=uuid4(),
        query="Question",
        expected_decision="can_answer",
        actual_decision="can_answer",
        passed=True,
        score=1.0,
    )

    assert document.visibility == ["public"]
    assert document.metadata_json == {}
    assert document.lifecycle_status == "active"
    assert document.lifecycle_reason is None
    assert section.metadata_json == {}
    assert chunk.metadata_json == {}
    assert background_job.status == "queued"
    assert background_job.priority == 100
    assert background_job.attempts == 0
    assert background_job.max_attempts == 3
    assert background_job.payload_json == {}
    assert background_job.result_json == {}
    assert indexing_job.stats_json == {}
    assert message.sources_json == []
    assert retrieval_event.selected_sources_json == []
    assert retrieval_event.scores_json == {}
    assert eval_case.expected_sources_json == []
    assert eval_case.tags_json == []
    assert eval_case.metadata_json == {}
    assert eval_case.source_kind == "manual"
    assert eval_case.seed_key == "seed.case"
    assert eval_case.promoted_feedback_id == feedback_id
    assert eval_run.trigger == "manual"
    assert eval_run.stats_json == {}
    assert eval_result.expected_sources_json == []
    assert eval_result.selected_sources_json == []
    assert eval_result.cited_sources_json == []
    assert eval_result.missing_sources_json == []
    assert eval_result.unexpected_sources_json == []
    assert eval_result.metrics_json == {}


def test_json_defaults_do_not_share_mutable_instances() -> None:
    first = Document(
        filename="a.md",
        canonical_path="docs/a.md",
        source_type="md",
        content_hash="a",
    )
    second = Document(
        filename="b.md",
        canonical_path="docs/b.md",
        source_type="md",
        content_hash="b",
    )

    first.visibility.append("staff")
    first.metadata_json["owner"] = "admin"

    assert second.visibility == ["public"]
    assert second.metadata_json == {}
