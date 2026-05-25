from collections.abc import Sequence
from hashlib import sha256
from typing import Protocol

from app.core.config import Settings


class EmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimension: int = 1536) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        encoded = text.encode("utf-8")
        values: list[float] = []
        counter = 0

        while len(values) < self.dimension:
            digest = sha256(encoded + counter.to_bytes(4, "big")).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            counter += 1

        return values[: self.dimension]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: str | None, model: str | None, dimension: int = 1536) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError(
            "OpenAI embeddings are intentionally deferred; Task 16 implements this adapter "
            "after checking the official OpenAI documentation."
        )


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider_name = settings.embedding_provider.lower()

    if provider_name == "fake":
        return FakeEmbeddingProvider(dimension=settings.embedding_dimension)

    if provider_name == "openai":
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dimension=settings.embedding_dimension,
        )

    raise ValueError(f"unsupported embedding provider: {settings.embedding_provider}")
