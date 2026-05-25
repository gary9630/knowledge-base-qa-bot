from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.indexing.service import IndexingService
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
        embedding_provider=FakeEmbeddingProvider(dimension=1536),
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

    with pytest.raises(ValueError, match="expected 1536 dimensions"):
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

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FakeEmbeddingProvider(dimension=1536),
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

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FakeEmbeddingProvider(dimension=1536),
    )

    with pytest.raises(FileNotFoundError, match="docs_dir does not exist"):
        service.rebuild_index()

    assert db_session.scalar(select(func.count()).select_from(Document)) == 1
    assert db_session.scalar(select(func.count()).select_from(Section)) == 0
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert (kb_dir / "index.json").read_text(encoding="utf-8") == old_export
    assert db_session.scalar(select(IndexingJob.status)) == "failed"


def _docs_dir_with_file(tmp_path: Path, filename: str, body: str) -> Path:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / filename).write_text(body, encoding="utf-8")
    return docs_dir
