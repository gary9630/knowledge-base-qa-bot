from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.indexing.export import DocumentExport, SectionExport, write_index_export
from app.indexing.markdown_parser import ParsedSection, parse_markdown_sections
from app.models.tables import Chunk, Document, IndexingJob, Section
from app.retrieval.embeddings import EmbeddingProvider


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
    ) -> None:
        self.session = session
        self.docs_dir = docs_dir
        self.kb_dir = kb_dir
        self.embedding_provider = embedding_provider

    def rebuild_index(self) -> IndexingResult:
        with self._transaction():
            job = IndexingJob(
                kind="rebuild",
                status="running",
                input_path=str(self.docs_dir),
                stats_json={},
            )
            self.session.add(job)
            self.session.flush()

            markdown_files = tuple(sorted(self.docs_dir.rglob("*.md")))
            indexed_filenames: set[str] = set()
            document_exports: list[DocumentExport] = []
            sections_indexed = 0
            chunks_indexed = 0

            self._delete_stale_documents(markdown_files)

            for path in markdown_files:
                document_export, section_count, chunk_count = self._index_file(path)
                indexed_filenames.add(document_export.filename)
                document_exports.append(document_export)
                sections_indexed += section_count
                chunks_indexed += chunk_count

            export_path = write_index_export(self.kb_dir, document_exports)
            result = IndexingResult(
                files_indexed=len(indexed_filenames),
                sections_indexed=sections_indexed,
                chunks_indexed=chunks_indexed,
                export_path=export_path,
            )
            job.status = "succeeded"
            job.stats_json = {
                "files_indexed": result.files_indexed,
                "sections_indexed": result.sections_indexed,
                "chunks_indexed": result.chunks_indexed,
                "export_path": str(result.export_path),
            }
            return result

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
        document = self.session.scalar(select(Document).where(Document.filename == filename))
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

        chunk = Chunk(
            section_id=section.id,
            chunk_index=0,
            body_text=body_md,
            token_count=_token_count(body_md),
            embedding=self.embedding_provider.embed_text(body_md),
            content_hash=content_hash,
        )
        self.session.add(chunk)
        return 1

    def _delete_stale_documents(self, markdown_files: tuple[Path, ...]) -> None:
        filenames = {_relative_filename(self.docs_dir, path) for path in markdown_files}
        documents = self.session.scalars(select(Document)).all()
        for document in documents:
            if document.filename not in filenames:
                self.session.delete(document)
        self.session.flush()

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
