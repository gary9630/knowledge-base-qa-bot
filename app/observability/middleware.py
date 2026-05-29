from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.metrics import InMemoryMetrics, RequestMetric

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_LOGGER_NAME = "app.observability.requests"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_STREAM_ERROR_STATE_KEY = "_kb_stream_error"


@dataclass(frozen=True)
class StreamErrorInfo:
    error_name: str
    detail: str | None = None
    exception: BaseException | None = None


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._logger = logging.getLogger(REQUEST_LOGGER_NAME)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        request_id = request_id_from_headers(request)
        request.state.request_id = request_id
        started_at = time.perf_counter()
        status_code = 500
        response_started = False
        recorded = False

        async def send_with_observability(message: Message) -> None:
            nonlocal recorded, response_started, status_code

            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message.get("status", 500))
                message = with_request_id_header(message, request_id)

            await send(message)

            if (
                message["type"] == "http.response.body"
                and not bool(message.get("more_body", False))
                and not recorded
            ):
                duration_ms = _elapsed_ms(started_at)
                stream_error = stream_error_from_request(request)
                if stream_error is None:
                    self._record_metric(
                        request,
                        request_id,
                        status_code,
                        duration_ms,
                        error=False,
                    )
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
                else:
                    self._record_handled_stream_error(
                        request,
                        request_id,
                        status_code,
                        duration_ms,
                        stream_error,
                    )
                recorded = True

        try:
            await self.app(scope, receive, send_with_observability)
        except BaseException as error:
            if not recorded:
                self._record_error(
                    request,
                    request_id,
                    status_code if response_started else 500,
                    _elapsed_ms(started_at),
                    error,
                    stream_error=response_started,
                )
                recorded = True
            raise

    def _record_error(
        self,
        request: Request,
        request_id: str,
        status_code: int,
        duration_ms: int,
        error: BaseException,
        *,
        stream_error: bool,
    ) -> None:
        self._record_metric(request, request_id, status_code, duration_ms, error=True)
        payload = {
            "event": "request_failed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "client": _client_host(request),
            "error": error.__class__.__name__,
        }
        if stream_error:
            payload["stream_error"] = True
        self._logger.error(
            _json_log(**payload),
            exc_info=error,
        )

    def _record_handled_stream_error(
        self,
        request: Request,
        request_id: str,
        status_code: int,
        duration_ms: int,
        error: StreamErrorInfo,
    ) -> None:
        self._record_metric(request, request_id, status_code, duration_ms, error=True)
        payload = {
            "event": "request_failed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "client": _client_host(request),
            "error": error.error_name,
            "stream_error": True,
            "handled": True,
        }
        if error.detail:
            payload["detail"] = error.detail
        self._logger.error(
            _json_log(**payload),
            exc_info=error.exception,
        )

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


def mark_stream_error(
    request: Request,
    error: BaseException,
    *,
    detail: str | None = None,
) -> None:
    setattr(
        request.state,
        _STREAM_ERROR_STATE_KEY,
        StreamErrorInfo(
            error_name=error.__class__.__name__,
            detail=detail,
            exception=error,
        ),
    )


def stream_error_from_request(request: Request) -> StreamErrorInfo | None:
    stream_error = getattr(request.state, _STREAM_ERROR_STATE_KEY, None)
    if isinstance(stream_error, StreamErrorInfo):
        return stream_error
    return None


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


def with_request_id_header(message: Message, request_id: str) -> Message:
    headers = [
        (name, value)
        for name, value in message.get("headers", [])
        if name.lower() != REQUEST_ID_HEADER.lower().encode("ascii")
    ]
    headers.append((REQUEST_ID_HEADER.encode("ascii"), request_id.encode("ascii")))
    return {**message, "headers": headers}


def _json_log(**payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _client_host(request: Request) -> str | None:
    return request.client.host if request.client is not None else None
