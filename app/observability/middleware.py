from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp

from app.observability.metrics import InMemoryMetrics, RequestMetric

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_LOGGER_NAME = "app.observability.requests"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._logger = logging.getLogger(REQUEST_LOGGER_NAME)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request_id_from_headers(request)
        request.state.request_id = request_id
        started_at = time.perf_counter()
        status_code = 500
        error_name: str | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as error:
            error_name = error.__class__.__name__
            duration_ms = _elapsed_ms(started_at)
            self._record_metric(request, request_id, status_code, duration_ms, error=True)
            self._logger.error(
                _json_log(
                    event="request_failed",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    client=_client_host(request),
                    error=error_name,
                ),
                exc_info=error,
            )
            raise

        duration_ms = _elapsed_ms(started_at)
        response.headers[REQUEST_ID_HEADER] = request_id
        self._record_metric(request, request_id, status_code, duration_ms, error=False)
        self._logger.info(
            _json_log(
                event="request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
                client=_client_host(request),
            )
        )
        return response

    def _record_metric(
        self,
        request: Request,
        request_id: str,
        status_code: int,
        duration_ms: int,
        *,
        error: bool,
    ) -> None:
        metrics = getattr(request.app.state, "metrics", None)
        if not isinstance(metrics, InMemoryMetrics):
            metrics = InMemoryMetrics()
            request.app.state.metrics = metrics
        metrics.record_request(
            RequestMetric(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                route=route_label(request),
                status_code=status_code,
                duration_ms=duration_ms,
            ),
            error=error,
        )


def create_request_id() -> str:
    return uuid4().hex


def request_id_from_headers(request: Request) -> str:
    incoming = request.headers.get(REQUEST_ID_HEADER)
    if incoming and _REQUEST_ID_RE.fullmatch(incoming):
        return incoming
    return create_request_id()


async def request_id_exception_handler(request: Request, _exc: Exception) -> Response:
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        request_id = create_request_id()

    response = PlainTextResponse("Internal Server Error", status_code=500)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def route_label(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return f"{request.method} {route_path}"
    return f"{request.method} <unmatched>"


def _json_log(**payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _client_host(request: Request) -> str | None:
    return request.client.host if request.client is not None else None
