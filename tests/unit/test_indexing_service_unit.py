from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session

from app.indexing.service import IndexingService
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
