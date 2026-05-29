from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

APP_DIR = Path(__file__).resolve().parents[1]
UI_DIR = APP_DIR / "ui"
STATIC_DIR = UI_DIR / "static"
TEMPLATES_DIR = UI_DIR / "templates"

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def mount_ui_static(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@router.get("/", include_in_schema=False)
def index(request: Request) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request},
    )
