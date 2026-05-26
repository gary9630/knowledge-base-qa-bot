from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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

    return app


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
