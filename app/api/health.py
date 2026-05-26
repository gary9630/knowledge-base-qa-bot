from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import require_admin_access
from app.observability.metrics import InMemoryMetrics

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics")
def metrics(
    request: Request,
    _: Annotated[None, Depends(require_admin_access)] = None,
) -> dict[str, Any]:
    metrics_store = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics_store, InMemoryMetrics):
        metrics_store = InMemoryMetrics()
        request.app.state.metrics = metrics_store
    return metrics_store.snapshot()
