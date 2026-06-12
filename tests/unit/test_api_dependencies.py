from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.api.dependencies import get_request_db_session, require_platform_access
from app.core.config import Settings


class ManagedSession:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self) -> ManagedSession:
        self.entered = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.exited = True


def test_request_db_session_uses_app_state_session_factory() -> None:
    session = ManagedSession()
    request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(session_factory=lambda: session),
            )
        ),
    )

    dependency = get_request_db_session(request)
    yielded: object = next(dependency)

    assert yielded is session
    assert session.entered
    with pytest.raises(StopIteration):
        next(dependency)
    assert session.exited


def test_platform_dependency_blocks_configured_requests_without_session() -> None:
    client = _platform_dependency_client(
        Settings(
            auth_secret_key="secret",
            platform_username="student",
            platform_password="pass",
        )
    )

    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == "Platform login is required."


def test_platform_dependency_allows_development_when_unconfigured() -> None:
    client = _platform_dependency_client(_unconfigured_auth_settings(app_env="development"))

    response = client.get("/protected")

    assert response.status_code == 200


def test_platform_dependency_fails_closed_in_production_when_unconfigured() -> None:
    client = _platform_dependency_client(_unconfigured_auth_settings(app_env="production"))

    response = client.get("/protected")

    assert response.status_code == 503
    assert response.json()["detail"] == "Platform auth is required but not configured."


def _unconfigured_auth_settings(*, app_env: str) -> Settings:
    # Explicit Nones so a developer's populated .env can't flip these tests.
    return Settings(
        app_env=app_env,
        auth_secret_key=None,
        platform_username=None,
        platform_password=None,
        admin_username=None,
        admin_password=None,
    )


def _platform_dependency_client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.state.settings = settings

    @app.get("/protected", dependencies=[Depends(require_platform_access)])
    def protected() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)
