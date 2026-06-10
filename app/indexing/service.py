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

from app.document_lifecycle import DOCUMENT_STATUS_ACTIVE
from app.indexing.export import (
    DocumentExport,
    SectionExport,
    build_index_export_payload,
    write_index_export_payload,
)
from app.indexing.frontmatter import parse_product_frontmatter
from app.indexing.markdown_parser import ParsedSection, parse_markdown_sections
from app.indexing.tokenization import DEFAULT_TOKEN_ENCODING, count_tokens, split_token_windows
from app.models.tables import Chunk, Document, IndexingJob, Section
from app.retrieval.dimensions import PGVECTOR_EMBEDDING_DIMENSION
from app.retrieval.embeddings import EmbeddingProvider

DEFAULT_CHUNK_TOKEN_LIMIT = 420
DEFAULT_CHUNK_OVERLAP = 64


@dataclass(frozen=True)
class IndexingResult:
    files_indexed: int
    sections_indexed: int
    chunks_indexed: int
    export_path: Path


class DocumentNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class _ChunkText:
    chunk_index: int
    body_text: str
    token_count: int
    content_hash: str
    start_token: int
    end_token: int


@dataclass(frozen=True)
class _ChunkBuildResult:
    chunks_indexed: int
    chunks_embedded: int
    chunks_reused: int


class IndexingService:
    def __init__(
        self,
        *,
        session: Session,
        docs_dir: Path,
        kb_dir: Path,
        embedding_provider: EmbeddingProvider,
        chunk_token_limit: int = DEFAULT_CHUNK_TOKEN_LIMIT,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        token_encoding: str = DEFAULT_TOKEN_ENCODING,
    ) -> None:
        if chunk_token_limit <= 0:
            raise ValueError("chunk_token_limit must be positive")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_token_limit:
            raise ValueError("chunk_overlap must be smaller than chunk_token_limit")

        self.session = session
        self.docs_dir = docs_dir
        self.kb_dir = kb_dir
        self.embedding_provider = embedding_provider
        self.chunk_token_limit = chunk_token_limit
        self.chunk_overlap = chunk_overlap
        self.token_encoding = token_encoding

    def rebuild_index(self) -> IndexingResult:
        if self.session.in_transaction():
            raise RuntimeError(
                "IndexingService.rebuild_index requires a session with no active transaction"
            )

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
                    (
                        document_export,
                        section_count,
                        chunk_count,
                        chunks_embedded,
                        chunks_reused,
                    ) = self._index_file(path)
                    indexed_filenames.add(document_export.filename)
                    if self._document_lifecycle_status(document_export.filename) == (
                        DOCUMENT_STATUS_ACTIVE
                    ):
                        document_exports.append(document_export)
                    else:
                        stats["files_skipped_lifecycle"] += 1
                    stats["files_indexed"] = len(indexed_filenames)
                    stats["sections_indexed"] += section_count
                    stats["chunks_indexed"] += chunk_count
                    stats["chunks_embedded"] += chunks_embedded
                    stats["chunks_reused"] += chunks_reused

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

    def reindex_document(self, document_id: UUID) -> IndexingResult:
        if self.session.in_transaction():
            raise RuntimeError(
                "IndexingService.reindex_document requires a session with no active transaction"
            )

        stats = _initial_stats()
        job_id: UUID | None = None
        try:
            self._validate_docs_dir()
            with self._transaction():
                document = self.session.get(Document, document_id)
                if document is None:
                    raise DocumentNotFoundError("Document not found.")

                path = Path(document.canonical_path)
                if not path.exists():
                    raise FileNotFoundError(f"Document source file does not exist: {path}")
                if not path.is_file():
                    raise FileNotFoundError(f"Document source path is not a file: {path}")

                job = IndexingJob(
                    kind="document_reindex",
                    status="running",
                    input_path=str(path),
                    stats_json=dict(stats),
                )
                self.session.add(job)
                self.session.flush()
                job_id = job.id

                document.lifecycle_status = DOCUMENT_STATUS_ACTIVE
                document.lifecycle_reason = None

                (
                    _document_export,
                    section_count,
                    chunk_count,
                    chunks_embedded,
                    chunks_reused,
                ) = self._index_file(path)
                stats["files_discovered"] = 1
                stats["files_indexed"] = 1
                stats["sections_indexed"] = section_count
                stats["chunks_indexed"] = chunk_count
                stats["chunks_embedded"] = chunks_embedded
                stats["chunks_reused"] = chunks_reused
                stats["export_path"] = str(self.kb_dir / "index.json")
                job.status = "indexed"
                job.stats_json = dict(stats)

            result = IndexingResult(
                files_indexed=1,
                sections_indexed=stats["sections_indexed"],
                chunks_indexed=stats["chunks_indexed"],
                export_path=self.kb_dir / "index.json",
            )
            self._mark_job_succeeded(job_id, stats)
            return result
        except Exception as error:
            self._persist_failed_job(error, stats, job_id=job_id)
            raise

    def _index_file(self, path: Path) -> tuple[DocumentExport, int, int, int, int]:
        filename = _relative_filename(self.docs_dir, path)
        body = path.read_text(encoding="utf-8")
        provenance = parse_product_frontmatter(body)
        parsed_sections = parse_markdown_sections(filename, body)
        document = self._upsert_document(path, filename, body, parsed_sections, provenance)
        self.session.flush()

        reusable_embeddings = self._existing_chunk_embeddings(document.id)
        stale_sections = self._existing_sections_by_source_id(document.id)

        section_exports: list[SectionExport] = []
        chunks_indexed = 0
        chunks_embedded = 0
        chunks_reused = 0
        for parsed_section in parsed_sections:
            section_hash = _content_hash(parsed_section.body_md)
            section = stale_sections.pop(parsed_section.source_id, None)
            section_unchanged = section is not None and section.content_hash == section_hash
            if section is None:
                section = Section(
                    document_id=document.id,
                    source_id=parsed_section.source_id,
                    heading=parsed_section.heading,
                    heading_slug=parsed_section.heading_slug,
                    level=parsed_section.level,
                    body_md=parsed_section.body_md,
                    token_count=count_tokens(
                        parsed_section.body_md, encoding_name=self.token_encoding
                    ),
                    content_hash=section_hash,
                )
                self.session.add(section)
            else:
                section.document_id = document.id
                section.heading = parsed_section.heading
                section.heading_slug = parsed_section.heading_slug
                section.level = parsed_section.level
                section.body_md = parsed_section.body_md
                section.token_count = count_tokens(
                    parsed_section.body_md, encoding_name=self.token_encoding
                )
                section.content_hash = section_hash

            self.session.flush()
            self.session.execute(
                update(Section)
                .where(Section.id == section.id)
                .values(tsv=func.to_tsvector("simple", Section.body_md))
            )

            existing_chunk_count = self._count_section_chunks(section.id)
            chunk_settings_current = self._section_chunk_settings_match(section.id)
            chunk_embeddings_present = self._section_chunk_embeddings_present(section.id)
            if (
                section_unchanged
                and existing_chunk_count > 0
                and chunk_settings_current
                and chunk_embeddings_present
            ):
                chunk_result = _ChunkBuildResult(
                    chunks_indexed=existing_chunk_count,
                    chunks_embedded=0,
                    chunks_reused=existing_chunk_count,
                )
            else:
                self.session.execute(delete(Chunk).where(Chunk.section_id == section.id))
                self.session.flush()
                chunk_result = self._create_chunks(
                    section,
                    parsed_section.body_md,
                    reusable_embeddings,
                )
            chunks_indexed += chunk_result.chunks_indexed
            chunks_embedded += chunk_result.chunks_embedded
            chunks_reused += chunk_result.chunks_reused
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

        for stale_section in stale_sections.values():
            self.session.delete(stale_section)
        self.session.flush()

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
            chunks_embedded,
            chunks_reused,
        )

    def _upsert_document(
        self,
        path: Path,
        filename: str,
        body: str,
        parsed_sections: list[ParsedSection],
        provenance: dict[str, str],
    ) -> Document:
        content_hash = _content_hash(body)
        document = self._get_canonical_document(filename)
        title = provenance.get("title") or (parsed_sections[0].heading if parsed_sections else None)
        source_type = provenance.get("source_type", "markdown")
        imported_from = provenance.get("source_original") if source_type == "imported" else None
        visibility = _visibility_from_provenance(provenance)
        metadata = dict(provenance)

        if document is None:
            document = Document(
                filename=filename,
                canonical_path=str(path),
                source_type=source_type,
                title=title,
                content_hash=content_hash,
                visibility=visibility,
                imported_from=imported_from,
                metadata_json=metadata,
            )
            self.session.add(document)
        else:
            document.canonical_path = str(path)
            document.source_type = source_type
            document.title = title
            document.content_hash = content_hash
            document.visibility = visibility
            document.imported_from = imported_from
            document.metadata_json = metadata

        return document

    def _create_chunks(
        self,
        section: Section,
        body_md: str,
        reusable_embeddings: dict[str, list[float]],
    ) -> _ChunkBuildResult:
        chunk_texts = split_section_chunks(
            body_md,
            token_limit=self.chunk_token_limit,
            overlap=self.chunk_overlap,
            encoding_name=self.token_encoding,
        )
        chunks_embedded = 0
        chunks_reused = 0

        for chunk_text in chunk_texts:
            embedding = reusable_embeddings.get(chunk_text.content_hash)
            if embedding is None:
                embedding = self.embedding_provider.embed_text(chunk_text.body_text)
                _validate_embedding_dimension(embedding)
                chunks_embedded += 1
            else:
                _validate_embedding_dimension(embedding)
                chunks_reused += 1

            chunk = Chunk(
                section_id=section.id,
                chunk_index=chunk_text.chunk_index,
                body_text=chunk_text.body_text,
                token_count=chunk_text.token_count,
                embedding=embedding,
                content_hash=chunk_text.content_hash,
                metadata_json={
                    "start_token": chunk_text.start_token,
                    "end_token": chunk_text.end_token,
                    "chunk_token_limit": self.chunk_token_limit,
                    "chunk_overlap": self.chunk_overlap,
                    "token_encoding": self.token_encoding,
                },
            )
            self.session.add(chunk)

        return _ChunkBuildResult(
            chunks_indexed=len(chunk_texts),
            chunks_embedded=chunks_embedded,
            chunks_reused=chunks_reused,
        )

    def _existing_chunk_embeddings(self, document_id: UUID) -> dict[str, list[float]]:
        reusable_embeddings: dict[str, list[float]] = {}
        statement = (
            select(Chunk.content_hash, Chunk.embedding)
            .join(Section, Section.id == Chunk.section_id)
            .where(Section.document_id == document_id)
            .where(Chunk.embedding.is_not(None))
        )
        for content_hash, embedding in self.session.execute(statement):
            if content_hash in reusable_embeddings or embedding is None:
                continue
            reusable_embeddings[content_hash] = [float(value) for value in embedding]
        return reusable_embeddings

    def _existing_sections_by_source_id(self, document_id: UUID) -> dict[str, Section]:
        sections = self.session.scalars(
            select(Section).where(Section.document_id == document_id)
        ).all()
        return {section.source_id: section for section in sections}

    def _count_section_chunks(self, section_id: UUID) -> int:
        count = self.session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.section_id == section_id)
        )
        return int(count or 0)

    def _section_chunk_settings_match(self, section_id: UUID) -> bool:
        metadata_rows = self.session.scalars(
            select(Chunk.metadata_json).where(Chunk.section_id == section_id)
        ).all()
        if not metadata_rows:
            return False

        return all(
            metadata.get("chunk_token_limit") == self.chunk_token_limit
            and metadata.get("chunk_overlap") == self.chunk_overlap
            and metadata.get("token_encoding") == self.token_encoding
            for metadata in metadata_rows
        )

    def _section_chunk_embeddings_present(self, section_id: UUID) -> bool:
        total_count = self._count_section_chunks(section_id)
        if total_count == 0:
            return False

        embedded_count = self.session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.section_id == section_id)
            .where(Chunk.embedding.is_not(None))
        )
        return int(embedded_count or 0) == total_count

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

    def _document_lifecycle_status(self, filename: str) -> str:
        status = self.session.scalar(
            select(Document.lifecycle_status)
            .where(Document.filename == filename)
            .order_by(Document.created_at.asc(), Document.id.asc())
            .limit(1)
        )
        return str(status or DOCUMENT_STATUS_ACTIVE)

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
            raise RuntimeError("IndexingService transaction requires an inactive session")

        with self.session.begin():
            yield


def _relative_filename(docs_dir: Path, path: Path) -> str:
    return path.relative_to(docs_dir).as_posix()


def _content_hash(body: str) -> str:
    return sha256(body.encode("utf-8")).hexdigest()


def _visibility_from_provenance(provenance: dict[str, str]) -> list[str]:
    raw_visibility = provenance.get("visibility")
    if not raw_visibility:
        return ["public"]

    normalized = (
        raw_visibility.replace("[", " ")
        .replace("]", " ")
        .replace(",", " ")
        .replace("'", " ")
        .replace('"', " ")
    )
    labels = [label.strip() for label in normalized.split() if label.strip()]
    return labels or ["public"]


def split_section_chunks(
    body_md: str,
    *,
    token_limit: int = DEFAULT_CHUNK_TOKEN_LIMIT,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
) -> list[_ChunkText]:
    windows = split_token_windows(
        body_md,
        token_limit=token_limit,
        overlap=overlap,
        encoding_name=encoding_name,
    )
    return [
        _ChunkText(
            chunk_index=index,
            body_text=window.text,
            token_count=window.token_count,
            content_hash=_content_hash(window.text),
            start_token=window.start_token,
            end_token=window.end_token,
        )
        for index, window in enumerate(windows)
    ]


def _validate_embedding_dimension(embedding: list[float]) -> None:
    if len(embedding) != PGVECTOR_EMBEDDING_DIMENSION:
        raise ValueError(
            f"embedding provider returned {len(embedding)} dimensions; "
            f"expected {PGVECTOR_EMBEDDING_DIMENSION} dimensions"
        )


def _initial_stats() -> dict[str, Any]:
    return {
        "files_discovered": 0,
        "files_indexed": 0,
        "files_skipped_lifecycle": 0,
        "sections_indexed": 0,
        "chunks_indexed": 0,
        "chunks_embedded": 0,
        "chunks_reused": 0,
    }
