from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest
from sqlalchemy.orm import Session

from app.retrieval.vector import VectorRetriever


class NoExecuteSession:
    def execute(self, statement: object) -> object:
        raise AssertionError("VectorRetriever should not execute SQL for this test")


class RecordingEmbeddingProvider:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding
        self.calls: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embedding

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


def test_vector_search_embeds_stripped_natural_query_before_db_access() -> None:
    provider = RecordingEmbeddingProvider([0.0] * 768)
    retriever = VectorRetriever(
        session=cast(Session, NoExecuteSession()),
        embedding_provider=provider,
    )

    result = retriever.search("  課程網站在哪？  ", limit=3)

    assert result == []
    assert provider.calls == ["課程網站在哪？"]


def test_vector_search_rejects_wrong_embedding_dimension_before_db_access() -> None:
    provider = RecordingEmbeddingProvider([0.0, 1.0])
    retriever = VectorRetriever(
        session=cast(Session, NoExecuteSession()),
        embedding_provider=provider,
    )

    with pytest.raises(ValueError, match="expected 768 dimensions"):
        retriever.search("課程網站在哪？", limit=3)

    assert provider.calls == ["課程網站在哪？"]
