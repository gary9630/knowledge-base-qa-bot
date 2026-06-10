from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from app.indexing.service import IndexingService
from app.models.tables import Chunk, Document, Section
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.vector import VectorRetriever


class StaticEmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        return [1.0, *([0.0] * 767)]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


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
        "# 課程公告\n\n## 上課時間\n\n每週三晚上上課。\n",
        encoding="utf-8",
    )
    embedding_provider = FakeEmbeddingProvider(dimension=768)
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


def test_vector_retriever_returns_best_chunk_evidence_after_indexing(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "長篇教材.md").write_text(
        "# 長篇教材\n\n"
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
        "retrieval-needle official-course-url nu xi omicron pi rho sigma tau\n",
        encoding="utf-8",
    )
    embedding_provider = FakeEmbeddingProvider(dimension=768)
    service = IndexingService(
        session=db_session,
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=embedding_provider,
        chunk_token_limit=12,
        chunk_overlap=3,
    )
    service.rebuild_index()

    retriever = HybridRetriever(
        session=db_session,
        embedding_provider=embedding_provider,
        score_threshold=0.0,
    )
    results = retriever.search("retrieval-needle", strategy="vector", limit=1, debug=True)

    assert results.decision == "can_answer"
    assert results[0].source_id == "長篇教材.md#長篇教材"
    assert results[0].debug_scores["chunk_index"] > 0
    assert "retrieval-needle" in results[0].body_md
    assert results[0].body_md != "# 長篇教材\n\n" + (
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
        "retrieval-needle official-course-url nu xi omicron pi rho sigma tau\n"
    )


def test_retriever_excludes_non_public_documents_by_default(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "staff-only.md").write_text(
        "---\n"
        "source_type: transcript\n"
        "visibility: staff\n"
        "---\n\n"
        "# Staff Only\n\n"
        "staffonlytoken should not be visible to public search.\n",
        encoding="utf-8",
    )
    embedding_provider = FakeEmbeddingProvider(dimension=768)
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
        score_threshold=0.0,
    )
    results = retriever.search("staffonlytoken", strategy="lexical", limit=3)

    assert results.decision == "cannot_confirm"
    assert results.candidates == []


def test_retriever_allows_configured_visibility_labels(
    db_session: Session,
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "staff-only.md").write_text(
        "---\n"
        "source_type: transcript\n"
        "visibility: staff\n"
        "---\n\n"
        "# Staff Only\n\n"
        "staffonlytoken should be visible to staff search.\n",
        encoding="utf-8",
    )
    embedding_provider = FakeEmbeddingProvider(dimension=768)
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
        visibility_labels=("public", "staff"),
        score_threshold=0.0,
    )
    results = retriever.search("staffonlytoken", strategy="lexical", limit=3)

    assert results.decision == "can_answer"
    assert results.candidates[0].source_id == "staff-only.md#staff-only"


def test_vector_retriever_fetches_more_rows_until_limit_unique_sections(
    db_session: Session,
) -> None:
    first_document = Document(
        filename="first.md",
        canonical_path="docs/first.md",
        source_type="markdown",
        title="First",
        content_hash="first-hash",
    )
    first_section = Section(
        document=first_document,
        source_id="first.md#first",
        heading="First",
        heading_slug="first",
        level=1,
        body_md="# First",
        token_count=2,
        content_hash="first-section-hash",
    )
    second_document = Document(
        filename="second.md",
        canonical_path="docs/second.md",
        source_type="markdown",
        title="Second",
        content_hash="second-hash",
    )
    second_section = Section(
        document=second_document,
        source_id="second.md#second",
        heading="Second",
        heading_slug="second",
        level=1,
        body_md="# Second",
        token_count=2,
        content_hash="second-section-hash",
    )
    db_session.add_all([first_document, second_document])
    db_session.flush()
    for chunk_index in range(10):
        db_session.add(
            Chunk(
                section=first_section,
                chunk_index=chunk_index,
                body_text=f"dominant chunk {chunk_index}",
                token_count=3,
                embedding=[1.0, *([0.0] * 767)],
                content_hash=f"first-chunk-{chunk_index}",
            )
        )
    db_session.add(
        Chunk(
            section=second_section,
            chunk_index=0,
            body_text="second section evidence",
            token_count=3,
            embedding=[0.99, 0.01, *([0.0] * 766)],
            content_hash="second-chunk",
        )
    )
    db_session.commit()

    retriever = VectorRetriever(
        session=db_session,
        embedding_provider=StaticEmbeddingProvider(),
    )

    results = retriever.search("query", limit=2)

    assert [candidate.source_id for candidate in results] == [
        "first.md#first",
        "second.md#second",
    ]
