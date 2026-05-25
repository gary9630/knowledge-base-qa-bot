from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.indexing.service import IndexingService
from app.models.tables import Chunk, Document, IndexingJob, Section
from app.retrieval.embeddings import FakeEmbeddingProvider


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
