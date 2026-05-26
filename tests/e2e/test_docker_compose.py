from __future__ import annotations

import json
import os
import urllib.request
import uuid

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
    _upload_text_file()
    _post_index()

    with urllib.request.urlopen("http://localhost:8000/ready", timeout=5) as response:
        ready_status = response.status
        ready_payload = json.loads(response.read().decode("utf-8"))
    metrics_request = urllib.request.Request(
        "http://localhost:8000/metrics",
        headers={"X-KB-Admin-Key": COMPOSE_ADMIN_API_KEY},
    )
    with urllib.request.urlopen(metrics_request, timeout=5) as response:
        metrics_status = response.status
        metrics_payload = json.loads(response.read().decode("utf-8"))

    assert ready_status == 200
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
    assert body["status"] == "succeeded"
    assert body["content_hash"]


def _upload_text_file() -> dict[str, object]:
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

    assert response.status == 200
    assert isinstance(body, dict)
    assert body["filename"] == filename
    assert body["canonical_path"].endswith(f"{filename.removesuffix('.txt')}.md")
    return body


def _post_index() -> dict[str, object]:
    request = urllib.request.Request(
        "http://localhost:8000/index",
        method="POST",
        headers={"X-KB-Admin-Key": COMPOSE_ADMIN_API_KEY},
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert isinstance(body, dict)
    return body
