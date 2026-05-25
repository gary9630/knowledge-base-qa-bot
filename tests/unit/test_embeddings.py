import pytest

from app.core.config import Settings
from app.retrieval.embeddings import (
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
    create_embedding_provider,
)


def _dot(first: list[float], second: list[float]) -> float:
    return sum(left * right for left, right in zip(first, second, strict=True))


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


def test_fake_embedding_provider_normalizes_vectors() -> None:
    provider = FakeEmbeddingProvider(dimension=256)

    vector = provider.embed_text("consistent hashing")

    assert _dot(vector, vector) == pytest.approx(1.0)


def test_fake_embedding_provider_has_lexical_locality() -> None:
    provider = FakeEmbeddingProvider(dimension=256)

    anchor = provider.embed_text("consistent hashing")
    related = provider.embed_text("consistent hashing ring")
    unrelated = provider.embed_text("refund policy")

    related_score = _dot(anchor, related)
    unrelated_score = _dot(anchor, unrelated)

    assert related_score > unrelated_score
    assert related_score > 0.5


def test_fake_embedding_provider_has_stable_expected_prefix() -> None:
    provider = FakeEmbeddingProvider(dimension=16)

    vector = provider.embed_text("consistent hashing")

    assert vector[:8] == pytest.approx(
        [
            0.0,
            -0.707106781187,
            0.0,
            0.0,
            -0.353553390593,
            0.0,
            0.0,
            -0.353553390593,
        ]
    )


def test_fake_embedding_provider_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        FakeEmbeddingProvider(dimension=0)


def test_embedding_provider_batch_default_embeds_each_text() -> None:
    provider = FakeEmbeddingProvider(dimension=8)

    batch = provider.embed_texts(["first", "second"])

    assert batch == [provider.embed_text("first"), provider.embed_text("second")]


def test_embedding_provider_batch_rejects_single_string() -> None:
    provider = FakeEmbeddingProvider(dimension=8)

    with pytest.raises(TypeError, match="embed_texts expects a sequence of text strings"):
        provider.embed_texts("abc")


def test_embedding_provider_factory_uses_fake_provider_from_settings() -> None:
    settings = Settings(embedding_provider="fake", embedding_dimension=12)

    provider = create_embedding_provider(settings)

    assert isinstance(provider, FakeEmbeddingProvider)
    assert len(provider.embed_text("configured dimension")) == 12


def test_embedding_provider_factory_uses_openai_placeholder_from_settings() -> None:
    settings = Settings(
        embedding_provider="openai",
        embedding_dimension=12,
        openai_api_key="test-key",
        openai_embedding_model="text-embedding-test",
    )

    provider = create_embedding_provider(settings)

    assert isinstance(provider, OpenAIEmbeddingProvider)


def test_embedding_provider_factory_rejects_unsupported_provider() -> None:
    settings = Settings(embedding_provider="unknown")

    with pytest.raises(ValueError, match="unsupported embedding provider: unknown"):
        create_embedding_provider(settings)


def test_openai_embedding_provider_placeholder_mentions_task_16() -> None:
    provider = OpenAIEmbeddingProvider(api_key="test-key", model="text-embedding-test", dimension=8)

    with pytest.raises(NotImplementedError, match="Task 16"):
        provider.embed_text("not yet implemented")
