import re
from collections.abc import Sequence
from hashlib import sha256
from math import sqrt
from typing import Protocol

from app.core.config import Settings

_BUCKETS_PER_TOKEN = 4
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


class EmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, str):
            raise TypeError("embed_texts expects a sequence of text strings, not a single str")
        return [self.embed_text(text) for text in texts]


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimension: int = 1536) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        values = [0.0] * self.dimension

        for token in _tokenize(text):
            for bucket_offset in range(_BUCKETS_PER_TOKEN):
                digest = sha256(f"{bucket_offset}:{token}".encode()).digest()
                bucket = int.from_bytes(digest[:8], "big") % self.dimension
                sign = 1.0 if digest[8] & 1 else -1.0
                values[bucket] += sign

        norm = sqrt(sum(value * value for value in values))
        if norm == 0.0:
            return values

        return [value / norm for value in values]


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


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())
