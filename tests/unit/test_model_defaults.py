from uuid import uuid4

from app.models import Chunk, Document, IndexingJob, Message, RetrievalEvent, Section


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
    indexing_job = IndexingJob(kind="index", status="pending")
    message = Message(conversation_id=uuid4(), role="assistant", content="Answer")
    retrieval_event = RetrievalEvent(
        query="Question",
        strategy="hybrid",
        decision="answered",
    )

    assert document.visibility == ["public"]
    assert document.metadata_json == {}
    assert section.metadata_json == {}
    assert chunk.metadata_json == {}
    assert indexing_job.stats_json == {}
    assert message.sources_json == []
    assert retrieval_event.selected_sources_json == []
    assert retrieval_event.scores_json == {}


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
