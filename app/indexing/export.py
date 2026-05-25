from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

INDEX_VERSION = 1


@dataclass(frozen=True)
class SectionExport:
    source_id: str
    filename: str
    heading: str
    heading_slug: str
    level: int
    body_md: str
    text: str
    content_hash: str


@dataclass(frozen=True)
class DocumentExport:
    filename: str
    canonical_path: str
    title: str | None
    content_hash: str
    sections: list[SectionExport]


def build_index_export_payload(documents: list[DocumentExport]) -> dict[str, Any]:
    return {
        "index_version": INDEX_VERSION,
        "built_at": datetime.now(UTC).isoformat(),
        "documents": [
            {
                **asdict(document),
                "sections": [asdict(section) for section in document.sections],
            }
            for document in documents
        ],
    }


def write_index_export(kb_dir: Path, documents: list[DocumentExport]) -> Path:
    return write_index_export_payload(kb_dir, build_index_export_payload(documents))


def write_index_export_payload(kb_dir: Path, payload: Mapping[str, Any]) -> Path:
    kb_dir.mkdir(parents=True, exist_ok=True)
    export_path = kb_dir / "index.json"
    temp_path = kb_dir / f".index.json.{uuid4().hex}.tmp"
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(export_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    return export_path
