from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_returns_request_snapshot() -> None:
    client = TestClient(create_app())
    client.get("/health")

    response = client.get("/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["requests_total"] >= 1
    assert "latest_requests" in body
    assert body["latest_requests"][0]["request_id"]


def test_metrics_requires_admin_key_when_configured() -> None:
    client = TestClient(create_app(settings=Settings(admin_api_key="secret")))
    client.get("/health")

    unauthorized_response = client.get("/metrics")
    authorized_response = client.get("/metrics", headers={"X-KB-Admin-Key": "secret"})

    assert unauthorized_response.status_code == 401
    assert authorized_response.status_code == 200
