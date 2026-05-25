from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.indexing.export import (
    DocumentExport,
    SectionExport,
    build_index_export_payload,
    write_index_export_payload,
)
from app.indexing.markdown_parser import ParsedSection, parse_markdown_sections
from app.models.tables import Chunk, Document, IndexingJob, Section
from app.retrieval.embeddings import EmbeddingProvider

DEFAULT_EMBEDDING_DIMENSION = 1536


@dataclass(frozen=True)
class IndexingResult:
    files_indexed: int
    sections_indexed: int
    chunks_indexed: int
    export_path: Path


class IndexingService:
    def __init__(
        self,
        *,
        session: Session,
        docs_dir: Path,
        kb_dir: Path,
        embedding_provider: EmbeddingProvider,
        embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
    ) -> None:
        self.session = session
        self.docs_dir = docs_dir
        self.kb_dir = kb_dir
        self.embedding_provider = embedding_provider
        self.embedding_dimension = embedding_dimension

    def rebuild_index(self) -> IndexingResult:
        stats = _initial_stats()
        job_id: UUID | None = None
        try:
            self._validate_docs_dir()
            with self._transaction():
                job = self._add_running_job(stats)
                job_id = job.id

                markdown_files = tuple(sorted(self.docs_dir.rglob("*.md")))
                stats["files_discovered"] = len(markdown_files)
                indexed_filenames: set[str] = set()
                document_exports: list[DocumentExport] = []

                self._delete_stale_documents(markdown_files)

                for path in markdown_files:
                    document_export, section_count, chunk_count = self._index_file(path)
                    indexed_filenames.add(document_export.filename)
                    document_exports.append(document_export)
                    stats["files_indexed"] = len(indexed_filenames)
                    stats["sections_indexed"] += section_count
                    stats["chunks_indexed"] += chunk_count

                export_payload = build_index_export_payload(document_exports)
                export_path = self.kb_dir / "index.json"
                stats["export_path"] = str(export_path)
                job.status = "indexed"
                job.stats_json = dict(stats)

            result = IndexingResult(
                files_indexed=len(indexed_filenames),
                sections_indexed=stats["sections_indexed"],
                chunks_indexed=stats["chunks_indexed"],
                export_path=export_path,
            )
            write_index_export_payload(self.kb_dir, export_payload)
            self._mark_job_succeeded(job_id, stats)
            return result
        except Exception as error:
            self._persist_failed_job(error, stats, job_id=job_id)
            raise

    def _index_file(self, path: Path) -> tuple[DocumentExport, int, int]:
        filename = _relative_filename(self.docs_dir, path)
        body = path.read_text(encoding="utf-8")
        parsed_sections = parse_markdown_sections(filename, body)
        document = self._upsert_document(path, filename, body, parsed_sections)
        self.session.flush()

        self.session.execute(delete(Section).where(Section.document_id == document.id))
        self.session.flush()

        section_exports: list[SectionExport] = []
        chunks_indexed = 0
        for parsed_section in parsed_sections:
            section_hash = _content_hash(parsed_section.body_md)
            section = Section(
                document_id=document.id,
                source_id=parsed_section.source_id,
                heading=parsed_section.heading,
                heading_slug=parsed_section.heading_slug,
                level=parsed_section.level,
                body_md=parsed_section.body_md,
                token_count=_token_count(parsed_section.body_md),
                content_hash=section_hash,
            )
            self.session.add(section)
            self.session.flush()
            self.session.execute(
                update(Section)
                .where(Section.id == section.id)
                .values(tsv=func.to_tsvector("simple", Section.body_md))
            )

            chunk_count = self._create_chunks(section, parsed_section.body_md, section_hash)
            chunks_indexed += chunk_count
            section_exports.append(
                SectionExport(
                    source_id=section.source_id,
                    filename=filename,
                    heading=section.heading,
                    heading_slug=section.heading_slug,
                    level=section.level,
                    body_md=section.body_md,
                    text=section.body_md,
                    content_hash=section.content_hash,
                )
            )

        return (
            DocumentExport(
                filename=filename,
                canonical_path=str(path),
                title=parsed_sections[0].heading if parsed_sections else None,
                content_hash=document.content_hash,
                sections=section_exports,
            ),
            len(parsed_sections),
            chunks_indexed,
        )

    def _upsert_document(
        self,
        path: Path,
        filename: str,
        body: str,
        parsed_sections: list[ParsedSection],
    ) -> Document:
        content_hash = _content_hash(body)
        document = self._get_canonical_document(filename)
        title = parsed_sections[0].heading if parsed_sections else None

        if document is None:
            document = Document(
                filename=filename,
                canonical_path=str(path),
                source_type="markdown",
                title=title,
                content_hash=content_hash,
                imported_from=None,
            )
            self.session.add(document)
        else:
            document.canonical_path = str(path)
            document.source_type = "markdown"
            document.title = title
            document.content_hash = content_hash

        return document

    def _create_chunks(self, section: Section, body_md: str, content_hash: str) -> int:
        if not body_md.strip():
            return 0

        embedding = self.embedding_provider.embed_text(body_md)
        if len(embedding) != self.embedding_dimension:
            raise ValueError(
                f"embedding provider returned {len(embedding)} dimensions; "
                f"expected {self.embedding_dimension} dimensions"
            )

        chunk = Chunk(
            section_id=section.id,
            chunk_index=0,
            body_text=body_md,
            token_count=_token_count(body_md),
            embedding=embedding,
            content_hash=content_hash,
        )
        self.session.add(chunk)
        return 1

    def _get_canonical_document(self, filename: str) -> Document | None:
        documents = self.session.scalars(
            select(Document)
            .where(Document.filename == filename)
            .order_by(Document.created_at.asc(), Document.id.asc())
        ).all()
        if not documents:
            return None

        canonical_document = documents[0]
        for duplicate_document in documents[1:]:
            self.session.delete(duplicate_document)
        self.session.flush()
        return canonical_document

    def _delete_stale_documents(self, markdown_files: tuple[Path, ...]) -> None:
        filenames = {_relative_filename(self.docs_dir, path) for path in markdown_files}
        documents = self.session.scalars(select(Document)).all()
        for document in documents:
            if document.filename not in filenames:
                self.session.delete(document)
        self.session.flush()

    def _validate_docs_dir(self) -> None:
        if not self.docs_dir.exists():
            raise FileNotFoundError(f"docs_dir does not exist: {self.docs_dir}")
        if not self.docs_dir.is_dir():
            raise NotADirectoryError(f"docs_dir is not a directory: {self.docs_dir}")

    def _add_running_job(self, stats: dict[str, Any]) -> IndexingJob:
        job = IndexingJob(
            kind="rebuild",
            status="running",
            input_path=str(self.docs_dir),
            stats_json=dict(stats),
        )
        self.session.add(job)
        self.session.flush()
        return job

    def _mark_job_succeeded(self, job_id: UUID | None, stats: dict[str, Any]) -> None:
        if job_id is None:
            return

        with self._transaction():
            job = self.session.get(IndexingJob, job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.error = None
            job.stats_json = dict(stats)

    def _persist_failed_job(
        self,
        error: Exception,
        stats: dict[str, Any],
        *,
        job_id: UUID | None = None,
    ) -> None:
        failure_stats = {
            **stats,
            "error_type": type(error).__name__,
        }
        with self._transaction():
            job = self.session.get(IndexingJob, job_id) if job_id is not None else None
            if job is None:
                job = IndexingJob(
                    kind="rebuild",
                    status="failed",
                    input_path=str(self.docs_dir),
                    stats_json=failure_stats,
                )
                self.session.add(job)
            else:
                job.status = "failed"
                job.stats_json = failure_stats
            job.error = str(error)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self.session.in_transaction():
            with self.session.begin_nested():
                yield
            return

        with self.session.begin():
            yield


def _relative_filename(docs_dir: Path, path: Path) -> str:
    return path.relative_to(docs_dir).as_posix()


def _content_hash(body: str) -> str:
    return sha256(body.encode("utf-8")).hexdigest()


def _token_count(body: str) -> int:
    return len(body.split())


def _initial_stats() -> dict[str, Any]:
    return {
        "files_discovered": 0,
        "files_indexed": 0,
        "sections_indexed": 0,
        "chunks_indexed": 0,
    }
