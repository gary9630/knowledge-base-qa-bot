from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import Chunk, Document, Section
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.models import RetrievedCandidate

PGVECTOR_EMBEDDING_DIMENSION = 1536


class VectorRetriever:
    def __init__(self, *, session: Session, embedding_provider: EmbeddingProvider) -> None:
        self.session = session
        self.embedding_provider = embedding_provider

    def search(self, query: str, limit: int = 5) -> list[RetrievedCandidate]:
        if limit <= 0 or not query.strip():
            return []

        query_embedding = self.embedding_provider.embed_text(query.strip())
        if len(query_embedding) != PGVECTOR_EMBEDDING_DIMENSION:
            raise ValueError(
                f"embedding provider returned {len(query_embedding)} dimensions; "
                f"expected {PGVECTOR_EMBEDDING_DIMENSION} dimensions"
            )
        if not any(value != 0.0 for value in query_embedding):
            return []

        distance = cast(Any, Chunk.embedding).cosine_distance(query_embedding)
        statement = (
            select(Section, Document, distance.label("vector_distance"))
            .join(Chunk, Chunk.section_id == Section.id)
            .join(Document, Document.id == Section.document_id)
            .where(Chunk.embedding.is_not(None))
            .order_by(distance.asc(), Section.created_at.asc(), Section.id.asc())
            .limit(max(limit * 4, limit))
        )

        best_by_section: dict[str, RetrievedCandidate] = {}
        for section, document, raw_distance in self.session.execute(statement):
            distance_value = float(raw_distance or 0.0)
            score = _cosine_distance_to_score(distance_value)
            candidate = RetrievedCandidate(
                section_id=section.id,
                source_id=section.source_id,
                filename=document.filename,
                heading=section.heading,
                body_md=section.body_md,
                score=score,
                strategy="vector",
                debug_scores={
                    "vector_distance": distance_value,
                    "vector_score": score,
                },
            )
            existing = best_by_section.get(str(section.id))
            if existing is None or candidate.score > existing.score:
                best_by_section[str(section.id)] = candidate

        return sorted(
            best_by_section.values(),
            key=lambda candidate: (-candidate.score, candidate.filename, candidate.source_id),
        )[:limit]


def _cosine_distance_to_score(distance: float) -> float:
    return min(1.0, max(0.0, 1.0 - distance))
