from __future__ import annotations

import time
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_app_settings,
    get_effective_settings,
    get_request_db_session,
    require_admin_access,
)
from app.api.indexing import latest_indexing_job, readiness_checks
from app.background_jobs.service import BackgroundJobService
from app.observability.metrics import InMemoryMetrics
from app.provider_budget import provider_budget_status

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin_access)])


class SystemCheck(BaseModel):
    name: str
    label: str
    status: str  # ok | warning | failed
    detail: str | None = None
    latency_ms: int | None = None


class SystemStatusResponse(BaseModel):
    overall: str
    uptime_seconds: int | None
    checked_at: str
    checks: list[SystemCheck]
    budget: dict[str, Any]


@router.get("/system-status", response_model=SystemStatusResponse)
def get_system_status(
    request: Request,
    session: Annotated[Session, Depends(get_request_db_session)],
) -> SystemStatusResponse:
    settings = get_app_settings(request)
    checks: list[SystemCheck] = []

    # Database round-trip
    started = perf_counter()
    try:
        session.execute(text("SELECT 1"))
        db_latency = round((perf_counter() - started) * 1000)
        checks.append(
            SystemCheck(
                name="database",
                label="資料庫",
                status="ok",
                detail="連線正常",
                latency_ms=db_latency,
            )
        )
        database_ok = True
    except Exception as error:
        checks.append(
            SystemCheck(
                name="database",
                label="資料庫",
                status="failed",
                detail=str(error),
            )
        )
        database_ok = False

    # Readiness checks (migrations, pgvector, storage, platform auth)
    if database_ok:
        try:
            ready = readiness_checks(session, settings=settings)
            for name, check in ready.items():
                if name in {"database", "index"}:
                    continue
                checks.append(
                    SystemCheck(
                        name=name,
                        label=_READY_CHECK_LABELS.get(name, name),
                        status="ok" if check.ok else "failed",
                        detail=check.detail,
                    )
                )
        except Exception as error:
            checks.append(
                SystemCheck(
                    name="readiness",
                    label="就緒檢查",
                    status="failed",
                    detail=str(error),
                )
            )

    # Index freshness
    if database_ok:
        try:
            job = latest_indexing_job(session)
            if job is None:
                checks.append(
                    SystemCheck(
                        name="index",
                        label="索引",
                        status="warning",
                        detail="尚未建立索引",
                    )
                )
            else:
                stats = job.stats_json or {}
                chunk_count = stats.get("chunks_indexed")
                checks.append(
                    SystemCheck(
                        name="index",
                        label="索引",
                        status="ok" if job.status == "succeeded" else "warning",
                        detail=(
                            f"狀態 {job.status}"
                            + (f" · {chunk_count} chunks" if chunk_count is not None else "")
                            + f" · 更新於 {job.updated_at.isoformat()}"
                        ),
                    )
                )
        except Exception as error:
            checks.append(
                SystemCheck(name="index", label="索引", status="failed", detail=str(error))
            )

    # Background worker heartbeats
    if database_ok:
        try:
            service = BackgroundJobService(session)
            now = datetime.now(UTC)
            workers = service.list_worker_heartbeats()
            stale_after = settings.worker_heartbeat_stale_after_seconds
            active = 0
            for worker in workers:
                last_seen = worker.last_seen_at
                if worker.status == "stopped" or last_seen is None:
                    continue
                age = (now - last_seen).total_seconds()
                if age <= stale_after:
                    active += 1
            queue = service.queue_counts()
            if active > 0:
                worker_status = "ok"
                worker_detail = f"{active} 個 worker 心跳正常"
            elif (queue.get("queued") or 0) > 0:
                worker_status = "warning"
                worker_detail = f"無活躍 worker，{queue.get('queued')} 個任務排隊中"
            else:
                worker_status = "warning"
                worker_detail = "無活躍 worker（背景任務不會執行）"
            checks.append(
                SystemCheck(
                    name="worker",
                    label="背景 Worker",
                    status=worker_status,
                    detail=f"{worker_detail} · queued {queue.get('queued', 0)} · running {queue.get('running', 0)}",
                )
            )
        except Exception as error:
            checks.append(
                SystemCheck(
                    name="worker",
                    label="背景 Worker",
                    status="failed",
                    detail=str(error),
                )
            )

    # Provider budget guardrail
    metrics = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics, InMemoryMetrics):
        metrics = InMemoryMetrics()
        request.app.state.metrics = metrics
    budget = provider_budget_status(
        get_effective_settings(request),
        metrics_snapshot=metrics.snapshot(),
    )
    budget_payload = budget.model_dump(mode="json")
    checks.append(
        SystemCheck(
            name="provider_budget",
            label="Provider 預算",
            status=(
                "failed"
                if budget.should_block
                else "warning"
                if budget.status == "warning"
                else "ok"
            ),
            detail=(
                "已超出預算並阻擋請求"
                if budget.should_block
                else f"狀態 {budget.status}"
            ),
        )
    )

    started_at = getattr(request.app.state, "started_at", None)
    uptime_seconds = (
        max(0, round(time.time() - started_at)) if isinstance(started_at, (int, float)) else None
    )

    overall = "ok"
    if any(check.status == "failed" for check in checks):
        overall = "failed"
    elif any(check.status == "warning" for check in checks):
        overall = "warning"

    return SystemStatusResponse(
        overall=overall,
        uptime_seconds=uptime_seconds,
        checked_at=datetime.now(UTC).isoformat(),
        checks=checks,
        budget=budget_payload,
    )


_READY_CHECK_LABELS = {
    "migrations": "資料庫遷移",
    "pgvector": "pgvector 擴充",
    "storage": "檔案儲存",
    "platform_auth": "平台登入設定",
}
