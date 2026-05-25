from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only, selectinload

from app.api.dependencies import get_request_db_session
from app.models.tables import Document, Section

router = APIRouter()


class MindmapNode(BaseModel):
    id: str
    type: Literal["document", "section"]
    label: str
    metadata: dict[str, object] = Field(default_factory=dict)


class MindmapEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str


class MindmapStats(BaseModel):
    documents: int
    sections: int


class MindmapResponse(BaseModel):
    nodes: list[MindmapNode]
    edges: list[MindmapEdge]
    stats: MindmapStats


@router.get("/mindmap", response_model=MindmapResponse)
def mindmap(session: Annotated[Session, Depends(get_request_db_session)]) -> MindmapResponse:
    documents = session.scalars(
        select(Document)
        .options(
            load_only(
                Document.id,
                Document.filename,
                Document.source_type,
                Document.title,
                Document.imported_from,
            ),
            selectinload(Document.sections).load_only(
                Section.id,
                Section.document_id,
                Section.source_id,
                Section.heading,
                Section.heading_slug,
                Section.level,
                Section.token_count,
            ),
        )
        .order_by(Document.filename.asc(), Document.id.asc())
    ).all()
    return build_mindmap_response(documents)


def build_mindmap_response(documents: Sequence[Document]) -> MindmapResponse:
    nodes: list[MindmapNode] = []
    edges: list[MindmapEdge] = []
    section_count = 0

    for document in documents:
        document_node_id = document_node_id_for(document)
        sections = sorted(document.sections, key=section_sort_key)
        section_count += len(sections)
        nodes.append(document_node(document, section_count=len(sections)))

        for section in sections:
            section_node_id = section_node_id_for(section)
            nodes.append(section_node(section))
            edges.append(
                MindmapEdge(
                    id=f"edge:{document.id}:{section.id}",
                    source=document_node_id,
                    target=section_node_id,
                    relation="contains",
                )
            )

    return MindmapResponse(
        nodes=nodes,
        edges=edges,
        stats=MindmapStats(documents=len(documents), sections=section_count),
    )


def document_node(document: Document, *, section_count: int) -> MindmapNode:
    return MindmapNode(
        id=document_node_id_for(document),
        type="document",
        label=document.title or document.filename,
        metadata={
            "document_id": str(document.id),
            "filename": document.filename,
            "title": document.title,
            "source_type": document.source_type,
            "imported_from": document.imported_from,
            "section_count": section_count,
        },
    )


def section_node(section: Section) -> MindmapNode:
    return MindmapNode(
        id=section_node_id_for(section),
        type="section",
        label=section.heading,
        metadata={
            "document_id": section_document_id_for(section),
            "section_id": str(section.id),
            "source_id": section.source_id,
            "heading": section.heading,
            "heading_slug": section.heading_slug,
            "level": section.level,
            "token_count": section.token_count,
        },
    )


def document_node_id_for(document: Document) -> str:
    return f"document:{document.id}"


def section_node_id_for(section: Section) -> str:
    return f"section:{section.id}"


def section_document_id_for(section: Section) -> str:
    if section.document_id is not None:
        return str(section.document_id)

    document = getattr(section, "document", None)
    if document is not None and document.id is not None:
        return str(document.id)

    return ""


def section_sort_key(section: Section) -> tuple[int, str, str, str]:
    return (section.level, section.heading_slug, section.source_id, str(section.id))
