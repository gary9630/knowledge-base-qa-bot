import re
from collections.abc import Sequence
from hashlib import sha256
from math import sqrt
from typing import Any, Protocol

from app.core.config import Settings
from app.retrieval.dimensions import PGVECTOR_EMBEDDING_DIMENSION

DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
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
    def __init__(self, dimension: int = PGVECTOR_EMBEDDING_DIMENSION) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        tokens = _tokenize(text)
        if not tokens and text != "":
            tokens = [text.casefold()]

        for token in tokens:
            for bucket_offset in range(_BUCKETS_PER_TOKEN):
                digest = sha256(f"{bucket_offset}:{token}".encode()).digest()
                bucket = int.from_bytes(digest[:8], "big") % self.dimension
                sign = 1.0 if digest[8] & 1 else -1.0
                values[bucket] += sign

        norm = sqrt(sum(value * value for value in values))
        if norm == 0.0:
            if tokens:
                digest = sha256(f"fallback:{' '.join(tokens)}".encode()).digest()
                bucket = int.from_bytes(digest[:8], "big") % self.dimension
                values[bucket] = 1.0
                return values
            return values

        return [value / norm for value in values]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        api_key: str | None,
        model: str | None,
        dimension: int = PGVECTOR_EMBEDDING_DIMENSION,
        *,
        client: object | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if client is None and not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embedding provider")

        self.model = model or DEFAULT_OPENAI_EMBEDDING_MODEL
        self.dimension = dimension
        self._client: Any = (
            client
            if client is not None
            else _openai_client(
                api_key,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        )

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, str):
            raise TypeError("embed_texts expects a sequence of text strings, not a single str")

        batch = list(texts)
        if not batch:
            raise ValueError("texts must not be empty")

        for index, text in enumerate(batch):
            if not isinstance(text, str):
                raise TypeError(f"text at index {index} must be a string")
            if not text.strip():
                raise ValueError(f"text at index {index} must not be empty")

        response = self._client.embeddings.create(
            model=self.model,
            input=batch,
            dimensions=self.dimension,
        )
        return _extract_embedding_vectors(
            response=response,
            expected_count=len(batch),
            expected_dimension=self.dimension,
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
            timeout_seconds=settings.openai_request_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )

    raise ValueError(f"unsupported embedding provider: {settings.embedding_provider}")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


def _openai_client(
    api_key: str | None,
    *,
    timeout_seconds: float,
    max_retries: int,
) -> Any:
    from openai import OpenAI

    return OpenAI(
        api_key=api_key,
        timeout=timeout_seconds,
        max_retries=max_retries,
    )


def _extract_embedding_vectors(
    *,
    response: object,
    expected_count: int,
    expected_dimension: int,
) -> list[list[float]]:
    data = getattr(response, "data", None)
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        raise ValueError("OpenAI embedding response did not include data")
    if len(data) != expected_count:
        raise ValueError(
            f"OpenAI embedding response returned {len(data)} vectors for {expected_count} inputs"
        )

    vectors: list[list[float]] = []
    for index, item in enumerate(data):
        embedding = getattr(item, "embedding", None)
        if not isinstance(embedding, Sequence) or isinstance(embedding, (str, bytes)):
            raise ValueError(f"OpenAI embedding response item {index} did not include embedding")
        vector = [float(value) for value in embedding]
        if len(vector) != expected_dimension:
            raise ValueError(
                f"OpenAI embedding response item {index} expected embedding dimension "
                f"{expected_dimension}, got {len(vector)}"
            )
        vectors.append(vector)

    return vectors
