from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request

from app.api.dependencies import get_request_db_session


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
