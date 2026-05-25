from pathlib import Path

import pytest

from app.indexing.export import DocumentExport, SectionExport, write_index_export


def test_write_index_export_replaces_existing_file_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    index_path = kb_dir / "index.json"
    old_payload = '{"old": true}\n'
    index_path.write_text(old_payload, encoding="utf-8")

    original_replace = Path.replace

    def fail_replace(self: Path, target: str | Path) -> Path:
        if self.name.startswith(".index.json."):
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_index_export(kb_dir, [_document_export()])

    assert index_path.read_text(encoding="utf-8") == old_payload
    assert list(kb_dir.glob(".index.json.*.tmp")) == []


def _document_export() -> DocumentExport:
    return DocumentExport(
        filename="guide.md",
        canonical_path="/tmp/guide.md",
        title="Guide",
        content_hash="doc-hash",
        sections=[
            SectionExport(
                source_id="guide.md#guide",
                filename="guide.md",
                heading="Guide",
                heading_slug="guide",
                level=1,
                body_md="# Guide\n",
                text="# Guide\n",
                content_hash="section-hash",
            )
        ],
    )
