from __future__ import annotations

from math import exp
from typing import Any, cast

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.tables import Document, Section
from app.retrieval.models import RetrievedCandidate, expanded_query_text


class LexicalRetriever:
    def __init__(self, *, session: Session, score_scale: float = 4.0) -> None:
        self.session = session
        self.score_scale = score_scale

    def search(self, query: str, limit: int = 5) -> list[RetrievedCandidate]:
        if limit <= 0 or not query.strip():
            return []

        search_text = expanded_query_text(query)
        if not search_text:
            return []

        tsquery = func.websearch_to_tsquery("simple", _websearch_or_query(search_text))
        rank = func.ts_rank_cd(Section.tsv, tsquery, 32)
        statement = (
            select(Section, Document, rank.label("lexical_rank"))
            .join(Document, Document.id == Section.document_id)
            .where(Section.tsv.is_not(None))
            .where(cast(Any, Section.tsv).op("@@")(tsquery))
            .order_by(desc(rank), Section.created_at.asc(), Section.id.asc())
            .limit(limit)
        )

        candidates: list[RetrievedCandidate] = []
        for section, document, raw_rank in self.session.execute(statement):
            raw_score = float(raw_rank or 0.0)
            score = _normalize_rank(raw_score, scale=self.score_scale)
            candidates.append(
                RetrievedCandidate(
                    section_id=section.id,
                    source_id=section.source_id,
                    filename=document.filename,
                    heading=section.heading,
                    body_md=section.body_md,
                    score=score,
                    strategy="lexical",
                    debug_scores={
                        "lexical_rank": raw_score,
                        "lexical_score": score,
                    },
                )
            )

        return candidates


def _websearch_or_query(search_text: str) -> str:
    terms = [term for term in search_text.split() if term]
    return " OR ".join(terms) if terms else search_text


def _normalize_rank(raw_rank: float, *, scale: float) -> float:
    if raw_rank <= 0.0:
        return 0.0
    return min(1.0, 1.0 - exp(-(raw_rank * scale)))
