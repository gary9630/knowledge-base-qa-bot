from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.indexing.service import IndexingService, split_section_chunks
from app.indexing.tokenization import count_tokens
from app.models.tables import Chunk, Document, IndexingJob, Section
from app.retrieval.embeddings import FakeEmbeddingProvider


class FailingEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        raise RuntimeError("embedding failed")

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class WrongDimensionEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class CountingEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self, dimension: int = 768) -> None:
        super().__init__(dimension=dimension)
        self.calls: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return super().embed_text(text)


def test_indexing_service_writes_documents_sections_chunks_and_export(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    (docs_dir / "常見問題FAQ.md").write_text(
        "# FAQ\n\n## 課程網站\n\n課程網站是 https://buildmoat.org/\n",
        encoding="utf-8",
    )

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FakeEmbeddingProvider(dimension=768),
    )

    result = service.rebuild_index()

    assert result.files_indexed == 1
    assert result.sections_indexed == 2
    assert result.chunks_indexed == 2
    assert (kb_dir / "index.json").exists()

    assert db_session.scalar(select(func.count()).select_from(Document)) == 1
    assert db_session.scalar(select(func.count()).select_from(Section)) == 2
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 2

    jobs = db_session.scalars(select(IndexingJob)).all()
    assert len(jobs) == 1
    assert jobs[0].kind == "rebuild"
    assert jobs[0].status == "succeeded"
    assert jobs[0].stats_json["files_indexed"] == 1
    db_session.commit()

    second_result = service.rebuild_index()

    assert second_result.files_indexed == 1
    assert second_result.sections_indexed == 2
    assert second_result.chunks_indexed == 2
    assert db_session.scalar(select(func.count()).select_from(Document)) == 1
    assert db_session.scalar(select(func.count()).select_from(Section)) == 2
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 2


def test_indexing_service_persists_failed_job_without_partial_rows(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = _docs_dir_with_file(tmp_path, "broken.md", "# Broken\n\nBody\n")
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    old_export = '{"old": true}\n'
    (kb_dir / "index.json").write_text(old_export, encoding="utf-8")

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FailingEmbeddingProvider(),
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        service.rebuild_index()

    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert db_session.scalar(select(func.count()).select_from(Section)) == 0
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert (kb_dir / "index.json").read_text(encoding="utf-8") == old_export

    jobs = db_session.scalars(select(IndexingJob)).all()
    assert len(jobs) == 1
    assert jobs[0].kind == "rebuild"
    assert jobs[0].status == "failed"
    assert jobs[0].input_path == str(docs_dir)
    assert "embedding failed" in (jobs[0].error or "")
    assert jobs[0].stats_json["files_discovered"] == 1


def test_indexing_service_rejects_active_session_transaction(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = _docs_dir_with_file(tmp_path, "active.md", "# Active\n")
    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=FakeEmbeddingProvider(dimension=768),
    )

    db_session.execute(select(Document))

    with pytest.raises(
        RuntimeError,
        match="IndexingService.rebuild_index requires a session with no active transaction",
    ):
        service.rebuild_index()


def test_indexing_service_rejects_wrong_embedding_dimension_before_export(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = _docs_dir_with_file(tmp_path, "wrong-dimension.md", "# Wrong\n\nBody\n")
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    old_export = '{"old": true}\n'
    (kb_dir / "index.json").write_text(old_export, encoding="utf-8")

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=WrongDimensionEmbeddingProvider(),
    )

    with pytest.raises(ValueError, match="expected 768 dimensions"):
        service.rebuild_index()

    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert db_session.scalar(select(func.count()).select_from(Section)) == 0
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert (kb_dir / "index.json").read_text(encoding="utf-8") == old_export
    assert db_session.scalar(select(IndexingJob.status)) == "failed"


def test_indexing_service_repairs_duplicate_documents_by_filename(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = _docs_dir_with_file(tmp_path, "duplicate.md", "# Duplicate\n\nBody\n")
    kb_dir = tmp_path / ".kb"
    db_session.add_all(
        [
            Document(
                filename="duplicate.md",
                canonical_path="/old/one.md",
                source_type="markdown",
                title="Old One",
                content_hash="old-one",
            ),
            Document(
                filename="duplicate.md",
                canonical_path="/old/two.md",
                source_type="markdown",
                title="Old Two",
                content_hash="old-two",
            ),
        ]
    )
    db_session.flush()
    db_session.commit()

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FakeEmbeddingProvider(dimension=768),
    )

    result = service.rebuild_index()

    documents = db_session.scalars(
        select(Document).where(Document.filename == "duplicate.md")
    ).all()
    assert result.files_indexed == 1
    assert len(documents) == 1
    assert documents[0].title == "Duplicate"
    assert db_session.scalar(select(func.count()).select_from(Section)) == 1
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 1


def test_indexing_service_persists_imported_document_provenance(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = _docs_dir_with_file(
        tmp_path,
        "imported.md",
        "---\n"
        'source_original: "raw/source guide.pdf"\n'
        "source_type: imported\n"
        "imported_at: 2026-05-26T12:00:00+00:00\n"
        "---\n\n"
        "# Imported Guide\n\nBody\n",
    )
    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=FakeEmbeddingProvider(dimension=768),
    )

    service.rebuild_index()

    document = db_session.scalar(select(Document).where(Document.filename == "imported.md"))
    assert document is not None
    assert document.source_type == "imported"
    assert document.imported_from == "raw/source guide.pdf"
    assert document.metadata_json == {
        "source_original": "raw/source guide.pdf",
        "source_type": "imported",
        "imported_at": "2026-05-26T12:00:00+00:00",
    }


def test_indexing_service_missing_docs_dir_does_not_delete_existing_state(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "missing-docs"
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    old_export = '{"old": true}\n'
    (kb_dir / "index.json").write_text(old_export, encoding="utf-8")
    db_session.add(
        Document(
            filename="existing.md",
            canonical_path="/old/existing.md",
            source_type="markdown",
            title="Existing",
            content_hash="existing-hash",
        )
    )
    db_session.flush()
    db_session.commit()

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FakeEmbeddingProvider(dimension=768),
    )

    with pytest.raises(FileNotFoundError, match="docs_dir does not exist"):
        service.rebuild_index()

    assert db_session.scalar(select(func.count()).select_from(Document)) == 1
    assert db_session.scalar(select(func.count()).select_from(Section)) == 0
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert (kb_dir / "index.json").read_text(encoding="utf-8") == old_export
    assert db_session.scalar(select(IndexingJob.status)) == "failed"


def test_indexing_service_splits_long_sections_into_ordered_chunks(
    db_session: Session,
    tmp_path: Path,
) -> None:
    token_limit = 10
    overlap = 3
    section_body = "# Chunking\n\n" + " ".join(f"token-{index}" for index in range(23)) + "\n"
    docs_dir = _docs_dir_with_file(tmp_path, "chunking.md", section_body)
    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=FakeEmbeddingProvider(dimension=768),
        chunk_token_limit=token_limit,
        chunk_overlap=overlap,
    )

    result = service.rebuild_index()

    chunks = db_session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc())).all()
    assert result.chunks_indexed == len(chunks)
    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.token_count <= token_limit for chunk in chunks)
    # token-level coverage: windows start at 0, advance by (limit - overlap), each
    # overlapping the previous window, and end at the section's final token
    assert chunks[0].metadata_json["start_token"] == 0
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.metadata_json["start_token"] == (
            previous.metadata_json["start_token"] + token_limit - overlap
        )
        assert current.metadata_json["start_token"] < previous.metadata_json["end_token"]
    assert chunks[-1].metadata_json["end_token"] == count_tokens(section_body.strip())
    assert len({chunk.content_hash for chunk in chunks}) == len(chunks)


def test_indexing_service_reuses_unchanged_chunk_embeddings_on_rebuild(
    db_session: Session,
    tmp_path: Path,
) -> None:
    body = "# Reuse\n\nalpha beta gamma delta epsilon zeta eta theta iota kappa lambda\n"
    docs_dir = _docs_dir_with_file(tmp_path, "reuse.md", body)
    provider = CountingEmbeddingProvider(dimension=768)
    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=provider,
        chunk_token_limit=8,
        chunk_overlap=3,
    )
    # the single section's body_md is the whole file, so the same splitter the
    # service uses yields the expected chunk count
    expected_count = len(split_section_chunks(body, token_limit=8, overlap=3))
    assert expected_count > 1

    first_result = service.rebuild_index()
    first_call_count = len(provider.calls)
    second_result = service.rebuild_index()

    assert first_result.chunks_indexed == expected_count
    assert second_result.chunks_indexed == expected_count
    assert first_call_count == expected_count
    assert len(provider.calls) == first_call_count
    jobs = db_session.scalars(select(IndexingJob).order_by(IndexingJob.created_at.asc())).all()
    assert jobs[-1].stats_json["chunks_reused"] == expected_count
    assert jobs[-1].stats_json["chunks_embedded"] == 0


def test_indexing_service_reembeds_unchanged_chunks_when_embeddings_are_missing(
    db_session: Session,
    tmp_path: Path,
) -> None:
    body = (
        "# Missing Embeddings\n\nalpha beta gamma delta epsilon zeta eta theta iota kappa lambda\n"
    )
    docs_dir = _docs_dir_with_file(tmp_path, "missing-embeddings.md", body)
    provider = CountingEmbeddingProvider(dimension=768)
    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=provider,
        chunk_token_limit=8,
        chunk_overlap=3,
    )
    expected_count = len(split_section_chunks(body, token_limit=8, overlap=3))
    assert expected_count > 1
    first_result = service.rebuild_index()
    assert first_result.chunks_indexed == expected_count

    provider.calls.clear()
    db_session.execute(update(Chunk).values(embedding=None))
    db_session.commit()

    second_result = service.rebuild_index()

    chunks = db_session.scalars(select(Chunk)).all()
    jobs = db_session.scalars(select(IndexingJob).order_by(IndexingJob.created_at.asc())).all()
    assert second_result.chunks_indexed == expected_count
    assert all(chunk.embedding is not None for chunk in chunks)
    assert len(provider.calls) == expected_count
    assert jobs[-1].stats_json["chunks_reused"] == 0
    assert jobs[-1].stats_json["chunks_embedded"] == expected_count


def test_indexing_service_preserves_unchanged_section_and_chunk_identity_on_rebuild(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = _docs_dir_with_file(
        tmp_path,
        "stable.md",
        "# Stable\n\nalpha beta gamma delta\n",
    )
    provider = CountingEmbeddingProvider(dimension=768)
    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=provider,
    )

    service.rebuild_index()
    first_section = db_session.scalar(
        select(Section).where(Section.source_id == "stable.md#stable")
    )
    assert first_section is not None
    first_chunk = db_session.scalar(select(Chunk).where(Chunk.section_id == first_section.id))
    assert first_chunk is not None
    db_session.commit()

    service.rebuild_index()

    second_section = db_session.scalar(
        select(Section).where(Section.source_id == "stable.md#stable")
    )
    assert second_section is not None
    second_chunk = db_session.scalar(select(Chunk).where(Chunk.section_id == second_section.id))
    assert second_chunk is not None
    assert second_section.id == first_section.id
    assert second_chunk.id == first_chunk.id
    assert len(provider.calls) == 1


def test_indexing_service_rechunks_when_chunk_settings_change(
    db_session: Session,
    tmp_path: Path,
) -> None:
    body = "# Settings\n\nalpha beta gamma delta epsilon zeta eta theta iota kappa lambda\n"
    docs_dir = _docs_dir_with_file(tmp_path, "settings.md", body)
    provider = CountingEmbeddingProvider(dimension=768)
    first_service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=provider,
        chunk_token_limit=8,
        chunk_overlap=3,
    )
    first_expected = [
        chunk.token_count for chunk in split_section_chunks(body, token_limit=8, overlap=3)
    ]
    assert len(first_expected) > 1
    first_service.rebuild_index()
    section = db_session.scalar(select(Section).where(Section.source_id == "settings.md#settings"))
    assert section is not None
    first_chunks = db_session.scalars(
        select(Chunk).where(Chunk.section_id == section.id).order_by(Chunk.chunk_index.asc())
    ).all()
    assert [chunk.token_count for chunk in first_chunks] == first_expected
    db_session.commit()

    second_service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=provider,
        chunk_token_limit=5,
        chunk_overlap=3,
    )
    second_expected = [
        chunk.token_count for chunk in split_section_chunks(body, token_limit=5, overlap=3)
    ]
    assert second_expected != first_expected
    second_service.rebuild_index()

    rechunked = db_session.scalars(
        select(Chunk).where(Chunk.section_id == section.id).order_by(Chunk.chunk_index.asc())
    ).all()
    assert [chunk.token_count for chunk in rechunked] == second_expected
    assert all(chunk.metadata_json["chunk_token_limit"] == 5 for chunk in rechunked)


def _docs_dir_with_file(tmp_path: Path, filename: str, body: str) -> Path:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / filename).write_text(body, encoding="utf-8")
    return docs_dir
