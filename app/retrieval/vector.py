from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.document_lifecycle import active_document_filter
from app.models.tables import Chunk, Document, Section
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.models import RetrievedCandidate, source_priority_for

PGVECTOR_EMBEDDING_DIMENSION = 1536


class VectorRetriever:
    def __init__(
        self,
        *,
        session: Session,
        embedding_provider: EmbeddingProvider,
        visibility_labels: Sequence[str] | None = ("public",),
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.visibility_labels = tuple(visibility_labels or ())

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
        base_statement = (
            select(Section, Document, Chunk, distance.label("vector_distance"))
            .join(Chunk, Chunk.section_id == Section.id)
            .join(Document, Document.id == Section.document_id)
            .where(Chunk.embedding.is_not(None))
            .where(active_document_filter())
            .order_by(
                distance.asc(),
                Section.created_at.asc(),
                Section.id.asc(),
                Chunk.chunk_index.asc(),
            )
        )
        base_statement = _apply_visibility_filter(base_statement, self.visibility_labels)

        best_by_section: dict[str, RetrievedCandidate] = {}
        fetch_limit = max(limit * 4, limit)
        offset = 0
        while len(best_by_section) < limit:
            rows = self.session.execute(base_statement.limit(fetch_limit).offset(offset)).all()
            if not rows:
                break

            for section, document, chunk, raw_distance in rows:
                distance_value = float(raw_distance or 0.0)
                score = _cosine_distance_to_score(distance_value)
                source_priority = source_priority_for(document.source_type, document.metadata_json)
                candidate = RetrievedCandidate(
                    section_id=section.id,
                    source_id=section.source_id,
                    filename=document.filename,
                    heading=section.heading,
                    body_md=chunk.body_text,
                    score=score,
                    strategy="vector",
                    source_type=document.source_type,
                    source_priority=source_priority,
                    debug_scores={
                        "chunk_index": float(chunk.chunk_index),
                        "chunk_token_count": float(chunk.token_count),
                        "vector_distance": distance_value,
                        "vector_score": score,
                    },
                )
                existing = best_by_section.get(str(section.id))
                if existing is None or candidate.score > existing.score:
                    best_by_section[str(section.id)] = candidate

            if len(rows) < fetch_limit:
                break
            offset += fetch_limit

        return sorted(
            best_by_section.values(),
            key=lambda candidate: (-candidate.score, candidate.filename, candidate.source_id),
        )[:limit]


def _cosine_distance_to_score(distance: float) -> float:
    return min(1.0, max(0.0, 1.0 - distance))


def _apply_visibility_filter(statement: Any, visibility_labels: tuple[str, ...]) -> Any:
    if not visibility_labels:
        return statement

    filters = [
        cast(Any, Document.visibility).contains([visibility_label])
        for visibility_label in visibility_labels
    ]
    return statement.where(or_(*filters))
