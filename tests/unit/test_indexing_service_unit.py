from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session

from app.indexing.service import IndexingService, split_section_chunks
from app.retrieval.embeddings import FakeEmbeddingProvider


class ActiveTransactionSession:
    def in_transaction(self) -> bool:
        return True


def test_rebuild_index_rejects_active_session_transaction(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    service = IndexingService(
        session=cast(Session, ActiveTransactionSession()),
        docs_dir=docs_dir,
        kb_dir=tmp_path / ".kb",
        embedding_provider=FakeEmbeddingProvider(),
    )

    with pytest.raises(
        RuntimeError,
        match="IndexingService.rebuild_index requires a session with no active transaction",
    ):
        service.rebuild_index()


def test_split_section_chunks_splits_long_chinese_section() -> None:
    body = "課程介紹分散式系統的核心概念，包括一致性、可用性與分區容忍。" * 80
    chunks = split_section_chunks(body, token_limit=420, overlap=64)

    assert len(chunks) > 1  # whitespace counting produced exactly 1 chunk before
    for chunk in chunks:
        assert chunk.token_count <= 420
        assert "�" not in chunk.body_text


def test_split_section_chunks_token_counts_use_tiktoken() -> None:
    body = "短的中文段落，不需要切分。"
    chunks = split_section_chunks(body, token_limit=420, overlap=64)

    assert len(chunks) == 1
    assert chunks[0].token_count > 5  # whitespace counting would say 1
