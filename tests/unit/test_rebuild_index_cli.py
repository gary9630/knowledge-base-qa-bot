from __future__ import annotations

import json
from contextlib import AbstractContextManager
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.indexing.service import IndexingResult
from app.retrieval.embeddings import EmbeddingProvider
from scripts.rebuild_index import main, rebuild_index


def test_rebuild_index_cli_returns_error_when_docs_dir_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        docs_dir=str(tmp_path / "missing-docs"),
        kb_dir=str(tmp_path / ".kb"),
    )

    exit_code = main([], settings=settings)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Docs directory does not exist" in captured.err


def test_rebuild_index_calls_indexing_service_with_settings_paths(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    settings = Settings(docs_dir=str(docs_dir), kb_dir=str(kb_dir))
    session = cast(Session, object())
    provider = cast(EmbeddingProvider, object())
    calls: dict[str, object] = {}

    class SessionContext(AbstractContextManager[Session]):
        def __enter__(self) -> Session:
            return session

        def __exit__(self, *args: object) -> None:
            return None

    class FakeIndexingService:
        def __init__(self, **kwargs: object) -> None:
            calls.update(kwargs)

        def rebuild_index(self) -> IndexingResult:
            return IndexingResult(
                files_indexed=2,
                sections_indexed=3,
                chunks_indexed=4,
                export_path=kb_dir / "index.json",
            )

    def service_factory(
        *,
        session: Session,
        docs_dir: Path,
        kb_dir: Path,
        embedding_provider: EmbeddingProvider,
    ) -> FakeIndexingService:
        return FakeIndexingService(
            session=session,
            docs_dir=docs_dir,
            kb_dir=kb_dir,
            embedding_provider=embedding_provider,
        )

    result = rebuild_index(
        settings=settings,
        session_factory=lambda: SessionContext(),
        embedding_provider=provider,
        service_factory=service_factory,
    )

    assert result.files_indexed == 2
    assert calls["session"] is session
    assert calls["docs_dir"] == docs_dir
    assert calls["kb_dir"] == kb_dir
    assert calls["embedding_provider"] is provider
    assert kb_dir.is_dir()


def test_rebuild_index_cli_prints_json_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs_dir = tmp_path / "docs"
    kb_dir = tmp_path / ".kb"
    docs_dir.mkdir()
    settings = Settings(docs_dir=str(docs_dir), kb_dir=str(kb_dir))

    def runner() -> IndexingResult:
        return IndexingResult(
            files_indexed=1,
            sections_indexed=2,
            chunks_indexed=3,
            export_path=kb_dir / "index.json",
        )

    exit_code = main([], settings=settings, runner=runner)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "indexed"
    assert payload["summary"]["files_indexed"] == 1
    assert payload["summary"]["chunks_indexed"] == 3
