from __future__ import annotations

import json
import os
import urllib.request
import uuid

import pytest


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
def test_docker_compose_upload_can_write_runtime_volumes() -> None:
    boundary = f"----kb-form-{uuid.uuid4().hex}"
    filename = f"compose-write-{uuid.uuid4().hex}.txt"
    payload = "\r\n".join(
        [
            f"--{boundary}",
            f'Content-Disposition: form-data; name="file"; filename="{filename}"',
            "Content-Type: text/plain",
            "",
            "Docker compose write check",
            f"--{boundary}--",
            "",
        ]
    ).encode("utf-8")

    request = urllib.request.Request(
        "http://localhost:8000/imports",
        data=payload,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert body["filename"] == filename
    assert body["canonical_path"].endswith(f"{filename.removesuffix('.txt')}.md")
