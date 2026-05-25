from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from pypdf.errors import PdfReadError

from app.api.dependencies import get_app_settings
from app.ingestion.service import import_file_to_markdown

router = APIRouter()


class ImportResponse(BaseModel):
    filename: str
    raw_path: str
    canonical_path: str


@router.post("/imports", response_model=ImportResponse)
async def import_upload(
    request: Request,
    file: Annotated[UploadFile, File()],
) -> ImportResponse:
    filename = _safe_filename(file.filename)
    body = await file.read()

    settings = get_app_settings(request)
    raw_dir = Path(settings.raw_dir)
    docs_dir = Path(settings.docs_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / filename
    canonical_path = docs_dir / f"{Path(filename).stem or 'document'}.md"
    if raw_path.exists() or canonical_path.exists():
        raise HTTPException(
            status_code=409,
            detail="Import destination already exists.",
        )

    try:
        markdown = import_file_to_markdown(
            filename,
            body,
            imported_at=datetime.now(UTC).isoformat(),
        )
    except (ValueError, UnicodeError, PdfReadError) as error:
        raise HTTPException(
            status_code=400,
            detail=f"Could not import file: {error}",
        ) from error

    raw_path.write_bytes(body)
    canonical_path.write_text(markdown, encoding="utf-8")

    return ImportResponse(
        filename=filename,
        raw_path=str(raw_path),
        canonical_path=str(canonical_path),
    )


def _safe_filename(filename: str | None) -> str:
    normalized = (filename or "").replace("\\", "/")
    name = PurePath(normalized).name
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Upload filename is required.")
    return name
