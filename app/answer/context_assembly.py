from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.indexing.tokenization import (
    DEFAULT_TOKEN_ENCODING,
    count_tokens,
    truncate_to_tokens,
)
from app.models.tables import Section
from app.retrieval.models import RetrievedCandidate

DEFAULT_NEIGHBOR_SECTIONS = 1
DEFAULT_CONTEXT_TOKEN_BUDGET = 8000


@dataclass(frozen=True)
class CandidateEntry:
    section_id: UUID
    source_id: str
    filename: str
    heading: str
    body_md: str
    score: float | None
    is_hit: bool
    neighbor_distance: int
    anchor_score: float
    token_count: int
    position: int | None
    truncated: bool = False


@dataclass(frozen=True)
class BudgetSelection:
    selected: list[CandidateEntry]
    tokens_used: int
    dropped_count: int
    truncated_count: int


@dataclass(frozen=True)
class ContextAssemblyDiagnostics:
    neighbor_window: int
    token_budget: int
    tokens_used: int
    hit_count: int
    neighbor_count: int
    dropped_count: int
    truncated_count: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "neighbor_window": self.neighbor_window,
            "token_budget": self.token_budget,
            "tokens_used": self.tokens_used,
            "hit_count": self.hit_count,
            "neighbor_count": self.neighbor_count,
            "dropped_count": self.dropped_count,
            "truncated_count": self.truncated_count,
        }


@dataclass(frozen=True)
class AssembledSource:
    section_id: UUID
    source_id: str
    filename: str
    heading: str
    body_md: str
    score: float | None
    is_hit: bool
    neighbor_distance: int
    truncated: bool


@dataclass(frozen=True)
class AssembledContext:
    sources: list[AssembledSource]
    diagnostics: ContextAssemblyDiagnostics


def select_within_budget(
    entries: Sequence[CandidateEntry],
    *,
    token_budget: int,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
) -> BudgetSelection:
    hits = sorted(
        (entry for entry in entries if entry.is_hit),
        key=lambda entry: -(entry.score or 0.0),
    )
    neighbors = sorted(
        (entry for entry in entries if not entry.is_hit),
        key=lambda entry: (entry.neighbor_distance, -entry.anchor_score),
    )

    selected: list[CandidateEntry] = []
    tokens_used = 0
    dropped_count = 0
    truncated_count = 0
    for entry in [*hits, *neighbors]:
        if tokens_used + entry.token_count <= token_budget:
            selected.append(entry)
            tokens_used += entry.token_count
            continue
        if not selected and entry.is_hit:
            truncated_body = truncate_to_tokens(
                entry.body_md,
                limit=token_budget,
                encoding_name=encoding_name,
            )
            truncated_tokens = count_tokens(truncated_body, encoding_name=encoding_name)
            selected.append(
                replace(
                    entry,
                    body_md=truncated_body,
                    token_count=truncated_tokens,
                    truncated=True,
                )
            )
            tokens_used += truncated_tokens
            truncated_count += 1
            continue
        dropped_count += 1

    return BudgetSelection(
        selected=selected,
        tokens_used=tokens_used,
        dropped_count=dropped_count,
        truncated_count=truncated_count,
    )


def order_for_output(entries: Sequence[CandidateEntry]) -> list[CandidateEntry]:
    best_hit_score: dict[str, float] = {}
    for entry in entries:
        score = entry.anchor_score
        best_hit_score[entry.filename] = max(best_hit_score.get(entry.filename, 0.0), score)

    def sort_key(entry: CandidateEntry) -> tuple[float, str, int, int, str]:
        position_known = 0 if entry.position is not None else 1
        return (
            -best_hit_score[entry.filename],
            entry.filename,
            position_known,
            entry.position if entry.position is not None else 0,
            entry.source_id,
        )

    return sorted(entries, key=sort_key)


class ContextAssembler:
    def __init__(
        self,
        *,
        session: Session,
        neighbor_sections: int = DEFAULT_NEIGHBOR_SECTIONS,
        token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
        encoding_name: str = DEFAULT_TOKEN_ENCODING,
    ) -> None:
        if neighbor_sections < 0:
            raise ValueError("neighbor_sections must be non-negative")
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        self.session = session
        self.neighbor_sections = neighbor_sections
        self.token_budget = token_budget
        self.encoding_name = encoding_name

    def assemble(self, candidates: Sequence[RetrievedCandidate]) -> AssembledContext:
        if not candidates:
            return AssembledContext(sources=[], diagnostics=self._diagnostics([], 0, 0, 0))

        entries = self._collect_entries(candidates)
        selection = select_within_budget(
            list(entries.values()),
            token_budget=self.token_budget,
            encoding_name=self.encoding_name,
        )
        ordered = order_for_output(selection.selected)
        sources = [
            AssembledSource(
                section_id=entry.section_id,
                source_id=entry.source_id,
                filename=entry.filename,
                heading=entry.heading,
                body_md=entry.body_md,
                score=entry.score,
                is_hit=entry.is_hit,
                neighbor_distance=entry.neighbor_distance,
                truncated=entry.truncated,
            )
            for entry in ordered
        ]
        return AssembledContext(
            sources=sources,
            diagnostics=self._diagnostics(
                ordered,
                selection.tokens_used,
                selection.dropped_count,
                selection.truncated_count,
            ),
        )

    def _collect_entries(
        self,
        candidates: Sequence[RetrievedCandidate],
    ) -> dict[UUID, CandidateEntry]:
        candidate_by_section: dict[UUID, RetrievedCandidate] = {
            candidate.section_id: candidate for candidate in candidates
        }
        sections = self.session.scalars(
            select(Section).where(Section.id.in_(list(candidate_by_section)))
        ).all()
        section_by_id = {section.id: section for section in sections}

        entries: dict[UUID, CandidateEntry] = {}
        for candidate in candidates:
            section = section_by_id.get(candidate.section_id)
            if section is None:
                # Section deleted between retrieval and assembly: fall back to the
                # candidate body so the answer path still works.
                entries[candidate.section_id] = self._entry_from_candidate(candidate)
                continue
            entries[section.id] = self._entry_from_section(
                section,
                score=candidate.score,
                is_hit=True,
                neighbor_distance=0,
                anchor_score=candidate.score,
                heading=candidate.heading,
                source_id=candidate.source_id,
                filename=candidate.filename,
            )

        if self.neighbor_sections > 0:
            for candidate in candidates:
                section = section_by_id.get(candidate.section_id)
                if section is None or section.position is None:
                    continue
                for neighbor in self._neighbors_for(section):
                    distance = abs((neighbor.position or 0) - (section.position or 0))
                    existing = entries.get(neighbor.id)
                    if existing is not None and (
                        existing.is_hit or existing.neighbor_distance <= distance
                    ):
                        continue
                    entries[neighbor.id] = self._entry_from_section(
                        neighbor,
                        score=None,
                        is_hit=False,
                        neighbor_distance=distance,
                        anchor_score=candidate.score,
                        heading=neighbor.heading,
                        source_id=neighbor.source_id,
                        filename=candidate.filename,
                    )
        return entries

    def _neighbors_for(self, section: Section) -> list[Section]:
        if section.position is None:
            return []
        return list(
            self.session.scalars(
                select(Section)
                .where(Section.document_id == section.document_id)
                .where(Section.position.is_not(None))
                .where(
                    Section.position.between(
                        section.position - self.neighbor_sections,
                        section.position + self.neighbor_sections,
                    )
                )
                .where(Section.id != section.id)
                .order_by(Section.position.asc())
            )
        )

    def _entry_from_section(
        self,
        section: Section,
        *,
        score: float | None,
        is_hit: bool,
        neighbor_distance: int,
        anchor_score: float,
        heading: str,
        source_id: str,
        filename: str,
    ) -> CandidateEntry:
        return CandidateEntry(
            section_id=section.id,
            source_id=source_id,
            filename=filename,
            heading=heading,
            body_md=section.body_md,
            score=score,
            is_hit=is_hit,
            neighbor_distance=neighbor_distance,
            anchor_score=anchor_score,
            token_count=count_tokens(section.body_md, encoding_name=self.encoding_name),
            position=section.position,
        )

    def _entry_from_candidate(self, candidate: RetrievedCandidate) -> CandidateEntry:
        return CandidateEntry(
            section_id=candidate.section_id,
            source_id=candidate.source_id,
            filename=candidate.filename,
            heading=candidate.heading,
            body_md=candidate.body_md,
            score=candidate.score,
            is_hit=True,
            neighbor_distance=0,
            anchor_score=candidate.score,
            token_count=count_tokens(candidate.body_md, encoding_name=self.encoding_name),
            position=None,
        )

    def _diagnostics(
        self,
        entries: list[CandidateEntry],
        tokens_used: int,
        dropped_count: int,
        truncated_count: int,
    ) -> ContextAssemblyDiagnostics:
        return ContextAssemblyDiagnostics(
            neighbor_window=self.neighbor_sections,
            token_budget=self.token_budget,
            tokens_used=tokens_used,
            hit_count=sum(1 for entry in entries if entry.is_hit),
            neighbor_count=sum(1 for entry in entries if not entry.is_hit),
            dropped_count=dropped_count,
            truncated_count=truncated_count,
        )
