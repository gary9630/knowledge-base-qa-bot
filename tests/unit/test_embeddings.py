import pytest

from app.core.config import Settings
from app.retrieval.embeddings import (
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
    create_embedding_provider,
)


def test_fake_embedding_provider_is_deterministic_and_1536_dimensional() -> None:
    provider = FakeEmbeddingProvider(dimension=1536)

    first = provider.embed_text("consistent hashing")
    second = provider.embed_text("consistent hashing")

    assert first == second
    assert len(first) == 1536
    assert any(value != 0 for value in first)


def test_fake_embedding_provider_differs_for_different_text() -> None:
    provider = FakeEmbeddingProvider(dimension=16)

    first = provider.embed_text("first document")
    second = provider.embed_text("second document")

    assert first != second
    assert all(-1.0 <= value <= 1.0 for value in first)
    assert all(-1.0 <= value <= 1.0 for value in second)


def test_fake_embedding_provider_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        FakeEmbeddingProvider(dimension=0)


def test_embedding_provider_batch_default_embeds_each_text() -> None:
    provider = FakeEmbeddingProvider(dimension=8)

    batch = provider.embed_texts(["first", "second"])

    assert batch == [provider.embed_text("first"), provider.embed_text("second")]


def test_embedding_provider_factory_uses_fake_provider_from_settings() -> None:
    settings = Settings(embedding_provider="fake", embedding_dimension=12)

    provider = create_embedding_provider(settings)

    assert isinstance(provider, FakeEmbeddingProvider)
    assert len(provider.embed_text("configured dimension")) == 12


def test_openai_embedding_provider_placeholder_mentions_task_16() -> None:
    provider = OpenAIEmbeddingProvider(api_key="test-key", model="text-embedding-test", dimension=8)

    with pytest.raises(NotImplementedError, match="Task 16"):
        provider.embed_text("not yet implemented")
