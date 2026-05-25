from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def write_index_export(kb_dir: Path, documents: list[DocumentExport]) -> Path:
    kb_dir.mkdir(parents=True, exist_ok=True)
    export_path = kb_dir / "index.json"
    payload: dict[str, Any] = {
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
    export_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return export_path
