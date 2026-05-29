from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

import pytest

COMPOSE_ADMIN_API_KEY = os.getenv("KB_ADMIN_API_KEY", "local-admin-key")


@pytest.mark.skipif(
    os.getenv("KB_DOCKER_E2E") != "1",
    reason="set KB_DOCKER_E2E=1 when docker compose is serving localhost:8000",
)
def test_docker_compose_health_endpoint() -> None:
    with urllib.request.urlopen("http://localhost:8000/health", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert payload == {"status": "ok"}


@pytest.mark.skipif(
    os.getenv("KB_DOCKER_E2E") != "1",
    reason="set KB_DOCKER_E2E=1 when docker compose is serving localhost:8000",
)
def test_docker_compose_ready_and_metrics_endpoints() -> None:
    _wait_for_worker_runtime()
    upload = _upload_text_file()
    _wait_for_import_finished(str(upload["id"]))
    ready_payload = _wait_for_ready()

    metrics_request = urllib.request.Request(
        "http://localhost:8000/metrics",
        headers={"X-KB-Admin-Key": COMPOSE_ADMIN_API_KEY},
    )
    with urllib.request.urlopen(metrics_request, timeout=5) as response:
        metrics_status = response.status
        metrics_payload = json.loads(response.read().decode("utf-8"))

    assert metrics_status == 200
    assert ready_payload["database"] is True
    assert ready_payload["ready"] is True
    assert ready_payload["checks"]["pgvector"]["ok"] is True
    assert ready_payload["checks"]["migrations"]["ok"] is True
    assert "requests_total" in metrics_payload
    assert "latest_requests" in metrics_payload


@pytest.mark.skipif(
    os.getenv("KB_DOCKER_E2E") != "1",
    reason="set KB_DOCKER_E2E=1 when docker compose is serving localhost:8000",
)
def test_docker_compose_upload_can_write_runtime_volumes() -> None:
    body = _upload_text_file()

    assert body["id"]
    assert body["status"] in {"queued", "succeeded"}
    assert body["content_hash"]


@pytest.mark.skipif(
    os.getenv("KB_DOCKER_E2E") != "1",
    reason="set KB_DOCKER_E2E=1 when docker compose is serving localhost:8000",
)
def test_docker_compose_worker_runtime_endpoint() -> None:
    _wait_for_worker_runtime()


def _upload_text_file() -> dict[str, Any]:
    boundary = f"----kb-form-{uuid.uuid4().hex}"
    filename = f"compose-write-{uuid.uuid4().hex}.txt"
    content = f"Docker compose write check {uuid.uuid4().hex}"
    payload = "\r\n".join(
        [
            f"--{boundary}",
            f'Content-Disposition: form-data; name="file"; filename="{filename}"',
            "Content-Type: text/plain",
            "",
            content,
            f"--{boundary}--",
            "",
        ]
    ).encode("utf-8")

    request = urllib.request.Request(
        "http://localhost:8000/imports",
        data=payload,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-KB-Admin-Key": COMPOSE_ADMIN_API_KEY,
        },
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))

    assert response.status in {200, 202}
    assert isinstance(body, dict)
    assert body["filename"] == filename
    assert body["canonical_path"].endswith(f"{filename.removesuffix('.txt')}.md")
    return body


def _wait_for_import_finished(job_id: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://localhost:8000/imports/{job_id}",
        headers={"X-KB-Admin-Key": COMPOSE_ADMIN_API_KEY},
    )
    deadline = time.monotonic() + 60
    last_payload: dict[str, Any] = {}

    while time.monotonic() < deadline:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert isinstance(payload, dict)

        last_payload = payload
        import_status = payload.get("status")
        if import_status in {"succeeded", "duplicate"}:
            return payload
        if import_status in {"failed", "canceled"}:
            raise AssertionError(f"import job reached terminal failure: {payload}")
        time.sleep(1)

    raise AssertionError(f"import job did not finish before timeout: {last_payload}")


def _wait_for_ready() -> dict[str, Any]:
    deadline = time.monotonic() + 60
    last_status: int | None = None
    last_payload: dict[str, Any] = {}

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:8000/ready", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                last_status = response.status
        except urllib.error.HTTPError as error:
            last_status = error.code
            payload = _http_error_payload(error)

        assert isinstance(payload, dict)
        last_payload = payload
        if last_status == 200 and payload.get("ready") is True:
            return payload
        time.sleep(1)

    raise AssertionError(
        f"ready endpoint did not become ready before timeout: "
        f"status={last_status} payload={last_payload}"
    )


def _http_error_payload(error: urllib.error.HTTPError) -> dict[str, Any]:
    body = error.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"body": body}
    return payload if isinstance(payload, dict) else {"body": payload}


def _wait_for_worker_runtime() -> dict[str, Any]:
    request = urllib.request.Request(
        "http://localhost:8000/admin/jobs/runtime",
        headers={"X-KB-Admin-Key": COMPOSE_ADMIN_API_KEY},
    )
    deadline = time.monotonic() + 30
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert isinstance(payload, dict)
        last_payload = payload
        if payload.get("active_workers", 0):
            return payload
        time.sleep(1)

    raise AssertionError(f"worker runtime never became active: {last_payload}")
