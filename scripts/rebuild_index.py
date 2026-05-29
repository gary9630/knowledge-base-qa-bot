from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import SessionLocal
from app.indexing.service import IndexingResult, IndexingService
from app.retrieval.embeddings import EmbeddingProvider, create_embedding_provider


class RebuildIndexService(Protocol):
    def rebuild_index(self) -> IndexingResult: ...


class IndexingServiceFactory(Protocol):
    def __call__(
        self,
        *,
        session: Session,
        docs_dir: Path,
        kb_dir: Path,
        embedding_provider: EmbeddingProvider,
    ) -> RebuildIndexService: ...


SessionFactory = Callable[[], AbstractContextManager[Session]]
IndexRunner = Callable[[], IndexingResult]


def rebuild_index(
    *,
    settings: Settings | None = None,
    session_factory: SessionFactory | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    service_factory: IndexingServiceFactory = IndexingService,
) -> IndexingResult:
    resolved_settings = settings or Settings()
    docs_dir = Path(resolved_settings.docs_dir)
    kb_dir = Path(resolved_settings.kb_dir)
    if not docs_dir.exists():
        raise FileNotFoundError(f"Docs directory does not exist: {docs_dir}")
    if not docs_dir.is_dir():
        raise NotADirectoryError(f"Docs path is not a directory: {docs_dir}")

    kb_dir.mkdir(parents=True, exist_ok=True)
    resolved_session_factory = session_factory or SessionLocal
    resolved_embedding_provider = embedding_provider or create_embedding_provider(
        resolved_settings
    )
    with resolved_session_factory() as session:
        service = service_factory(
            session=session,
            docs_dir=docs_dir,
            kb_dir=kb_dir,
            embedding_provider=resolved_embedding_provider,
        )
        return service.rebuild_index()


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    runner: IndexRunner | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the Postgres + pgvector index from configured docs."
    )
    parser.add_argument("--docs-dir", type=Path)
    parser.add_argument("--kb-dir", type=Path)
    namespace = parser.parse_args(argv)

    resolved_settings = settings or Settings()
    settings_updates: dict[str, str] = {}
    if namespace.docs_dir is not None:
        settings_updates["docs_dir"] = str(namespace.docs_dir)
    if namespace.kb_dir is not None:
        settings_updates["kb_dir"] = str(namespace.kb_dir)
    if settings_updates:
        resolved_settings = resolved_settings.model_copy(update=settings_updates)

    try:
        result = runner() if runner is not None else rebuild_index(settings=resolved_settings)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "indexed",
                "summary": {
                    "files_indexed": result.files_indexed,
                    "sections_indexed": result.sections_indexed,
                    "chunks_indexed": result.chunks_indexed,
                    "export_path": str(result.export_path),
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
