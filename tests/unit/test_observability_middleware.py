from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse
from starlette.types import Message, Receive, Scope, Send

from app.observability.metrics import InMemoryMetrics
from app.observability.middleware import (
    REQUEST_LOGGER_NAME,
    RequestObservabilityMiddleware,
    request_id_exception_handler,
)


def test_request_observability_generates_request_id_and_records_metrics() -> None:
    app = _observed_app()
    client = TestClient(app)

    with _captured_request_logs(logging.INFO) as records:
        response = client.get("/ok")

    request_id = response.headers["X-Request-ID"]
    metrics = app.state.metrics.snapshot()
    log_payloads = [_json_log(record.message) for record in records]

    assert response.status_code == 200
    assert len(request_id) >= 16
    assert metrics["requests_total"] == 1
    assert metrics["responses_by_status"] == {"200": 1}
    assert metrics["responses_by_route"] == {"GET /ok": 1}
    assert metrics["errors_total"] == 0
    assert metrics["average_latency_ms"] >= 0
    assert metrics["latest_requests"][0]["request_id"] == request_id
    assert log_payloads[0]["event"] == "request_completed"
    assert log_payloads[0]["request_id"] == request_id
    assert log_payloads[0]["method"] == "GET"
    assert log_payloads[0]["path"] == "/ok"
    assert log_payloads[0]["status_code"] == 200


def test_request_observability_preserves_valid_incoming_request_id() -> None:
    app = _observed_app()
    client = TestClient(app)

    response = client.get("/ok", headers={"X-Request-ID": "client-request-123"})

    assert response.headers["X-Request-ID"] == "client-request-123"
    assert app.state.metrics.snapshot()["latest_requests"][0]["request_id"] == "client-request-123"


def test_request_observability_logs_and_records_unhandled_errors() -> None:
    app = _observed_app()
    client = TestClient(app, raise_server_exceptions=False)

    with _captured_request_logs(logging.ERROR) as records:
        response = client.get("/boom", headers={"X-Request-ID": "boom-request"})

    metrics = app.state.metrics.snapshot()
    log_payloads = [_json_log(record.message) for record in records]

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "boom-request"
    assert metrics["requests_total"] == 1
    assert metrics["responses_by_status"] == {"500": 1}
    assert metrics["errors_total"] == 1
    assert log_payloads[0]["event"] == "request_failed"
    assert log_payloads[0]["request_id"] == "boom-request"
    assert log_payloads[0]["error"] == "RuntimeError"
    assert records[0].exc_info is not None


def test_request_observability_reraises_unhandled_errors_after_recording() -> None:
    app = _observed_app()
    client = TestClient(app)

    with pytest.raises(RuntimeError, match="boom"):
        client.get("/boom", headers={"X-Request-ID": "boom-request"})

    metrics = app.state.metrics.snapshot()

    assert metrics["requests_total"] == 1
    assert metrics["responses_by_status"] == {"500": 1}
    assert metrics["errors_total"] == 1


def test_request_observability_uses_route_templates_for_metrics() -> None:
    app = _observed_app()
    client = TestClient(app)

    response = client.get("/items/123")

    assert response.status_code == 200
    assert app.state.metrics.snapshot()["responses_by_route"] == {"GET /items/{item_id}": 1}


def test_request_observability_records_streaming_completion_after_body_finishes() -> None:
    app = _observed_app()
    client = TestClient(app)

    with _captured_request_logs(logging.INFO) as records:
        response = client.get("/stream")

    metrics = app.state.metrics.snapshot()
    log_payloads = [_json_log(record.message) for record in records]

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.text == "first\nsecond\n"
    assert metrics["requests_total"] == 1
    assert metrics["latest_requests"][0]["duration_ms"] >= 40
    assert len(log_payloads) == 1
    assert log_payloads[0]["event"] == "request_completed"
    logged_duration = log_payloads[0]["duration_ms"]
    assert isinstance(logged_duration, int)
    assert logged_duration >= 40


def test_request_observability_records_late_streaming_errors() -> None:
    app = _observed_app()
    client = TestClient(app, raise_server_exceptions=False)

    with _captured_request_logs(logging.ERROR) as records:
        response = client.get("/stream-boom", headers={"X-Request-ID": "stream-request"})

    metrics = app.state.metrics.snapshot()
    log_payloads = [_json_log(record.message) for record in records]

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "stream-request"
    assert metrics["requests_total"] == 1
    assert metrics["responses_by_status"] == {"200": 1}
    assert metrics["errors_total"] == 1
    assert metrics["latest_requests"][0]["request_id"] == "stream-request"
    assert metrics["latest_requests"][0]["status_code"] == 200
    assert log_payloads[0]["event"] == "request_failed"
    assert log_payloads[0]["request_id"] == "stream-request"
    assert log_payloads[0]["status_code"] == 200
    assert log_payloads[0]["stream_error"] is True
    assert log_payloads[0]["error"] == "RuntimeError"
    assert records[0].exc_info is not None


@pytest.mark.asyncio
async def test_request_observability_records_stream_cancellation() -> None:
    app = FastAPI()
    app.state.metrics = InMemoryMetrics()
    sent_messages: list[Message] = []

    async def cancelled_stream_app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send(
            {
                "type": "http.response.body",
                "body": b"first\n",
                "more_body": True,
            }
        )
        raise asyncio.CancelledError()

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent_messages.append(message)

    middleware = RequestObservabilityMiddleware(cancelled_stream_app)
    with _captured_request_logs(logging.ERROR) as records:
        with pytest.raises(asyncio.CancelledError):
            await middleware(_http_scope(app, path="/cancelled"), receive, send)

    metrics = app.state.metrics.snapshot()
    log_payloads = [_json_log(record.message) for record in records]

    assert sent_messages[0]["type"] == "http.response.start"
    assert metrics["requests_total"] == 1
    assert metrics["errors_total"] == 1
    assert metrics["responses_by_status"] == {"200": 1}
    assert log_payloads[0]["event"] == "request_failed"
    assert log_payloads[0]["stream_error"] is True
    assert log_payloads[0]["error"] == "CancelledError"


def _observed_app() -> FastAPI:
    app = FastAPI()
    app.state.metrics = InMemoryMetrics()
    app.add_middleware(RequestObservabilityMiddleware)
    app.add_exception_handler(Exception, request_id_exception_handler)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    @app.get("/items/{item_id}")
    def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/stream")
    def stream() -> StreamingResponse:
        def generate() -> Iterator[str]:
            yield "first\n"
            time.sleep(0.05)
            yield "second\n"

        return StreamingResponse(generate(), media_type="text/plain")

    @app.get("/stream-boom")
    def stream_boom() -> StreamingResponse:
        def generate() -> Iterator[str]:
            yield "first\n"
            raise RuntimeError("stream boom")

        return StreamingResponse(generate(), media_type="text/plain")

    return app


def _http_scope(app: FastAPI, *, path: str) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {},
        "app": app,
    }


def _json_log(message: str) -> dict[str, object]:
    payload = json.loads(message)
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


class _ListHandler(logging.Handler):
    def __init__(self, level: int) -> None:
        super().__init__(level)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _captured_request_logs(level: int) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger(REQUEST_LOGGER_NAME)
    handler = _ListHandler(level)
    previous_level = logger.level
    previous_disabled = logger.disabled
    previous_global_disable = logging.root.manager.disable
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.disabled = False
    logging.disable(logging.NOTSET)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.disabled = previous_disabled
        logging.disable(previous_global_disable)
