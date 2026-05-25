from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.indexing.service import IndexingService
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.hybrid import HybridRetriever


def test_hybrid_retriever_finds_course_site_section_after_indexing(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "常見問題FAQ.md").write_text(
        "# FAQ\n\n"
        "## 課程網站\n\n"
        "課程網站是 https://buildmoat.org/\n\n"
        "## 作業繳交\n\n"
        "請依公告時間繳交作業。\n",
        encoding="utf-8",
    )
    (docs_dir / "課程公告.md").write_text(
        "# 課程公告\n\n"
        "## 上課時間\n\n"
        "每週三晚上上課。\n",
        encoding="utf-8",
    )
    embedding_provider = FakeEmbeddingProvider(dimension=1536)
    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=embedding_provider,
    )
    service.rebuild_index()

    retriever = HybridRetriever(
        session=db_session,
        embedding_provider=embedding_provider,
        score_threshold=0.05,
    )
    results = retriever.search("課程網站在哪？", strategy="hybrid", limit=3)

    assert results.decision == "can_answer"
    assert results[0].source_id == "常見問題FAQ.md#課程網站"
    assert results[0].filename == "常見問題FAQ.md"
    assert results[0].heading == "課程網站"
