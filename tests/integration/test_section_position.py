from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indexing.service import IndexingService
from app.models.tables import Section
from app.retrieval.embeddings import FakeEmbeddingProvider


def test_rebuild_index_writes_document_order_positions(
    db_session: Session, tmp_path: Path
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    (docs_dir / "course.md").write_text(
        "# 課程簡介\n\n第一段。\n\n## 評分方式\n\n第二段。\n\n## 課程網站\n\n第三段。\n",
        encoding="utf-8",
    )

    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=kb_dir,
        embedding_provider=FakeEmbeddingProvider(),
    )
    service.rebuild_index()

    sections = db_session.scalars(
        select(Section).order_by(Section.position.asc())
    ).all()
    assert [section.position for section in sections] == [0, 1, 2]
    assert sections[0].heading == "課程簡介"
    assert sections[2].heading == "課程網站"
