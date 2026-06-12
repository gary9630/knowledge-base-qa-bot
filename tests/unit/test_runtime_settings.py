from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.runtime_settings import (
    RUNTIME_SETTING_KEYS,
    apply_runtime_overrides,
    runtime_setting_defaults,
    validate_runtime_overrides,
)


def _settings(**kwargs: object) -> Settings:
    base: dict[str, Any] = {
        "embedding_provider": "fake",
        "answer_provider": "fake",
        "auth_secret_key": None,
        "platform_username": None,
        "platform_password": None,
        "admin_username": None,
        "admin_password": None,
        "admin_api_key": None,
    }
    base.update(kwargs)
    return Settings(**base)


def test_validate_runtime_overrides_drops_nones_and_keeps_values() -> None:
    validated = validate_runtime_overrides(
        {
            "openai_chat_model": "gpt-5.4-mini",
            "openai_chat_temperature": None,
        }
    )

    assert validated == {"openai_chat_model": "gpt-5.4-mini"}


def test_validate_runtime_overrides_rejects_unknown_keys_and_bad_values() -> None:
    with pytest.raises(ValidationError):
        validate_runtime_overrides({"not_a_setting": 1})

    with pytest.raises(ValidationError):
        validate_runtime_overrides({"openai_chat_temperature": 9.0})

    with pytest.raises(ValidationError):
        validate_runtime_overrides({"openai_chat_max_completion_tokens": 0})


def test_apply_runtime_overrides_layers_on_top_of_env_settings() -> None:
    settings = _settings(openai_chat_max_completion_tokens=1024)

    effective = apply_runtime_overrides(
        settings,
        {
            "openai_chat_model": "gpt-override",
            "openai_chat_max_completion_tokens": 2048,
            "provider_budget_daily_call_limit": 50,
        },
    )

    assert effective.openai_chat_model == "gpt-override"
    assert effective.openai_chat_max_completion_tokens == 2048
    assert effective.provider_budget_daily_call_limit == 50
    # untouched values pass through
    assert effective.answer_provider == "fake"
    # original settings object is not mutated
    assert settings.openai_chat_model != "gpt-override"


def test_runtime_setting_defaults_exposes_allowlist_only() -> None:
    defaults = runtime_setting_defaults(_settings())
    assert set(defaults) == set(RUNTIME_SETTING_KEYS)


def _client_with_memory_store(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, dict[str, object]]:
    """Client whose /admin/settings persistence is an in-memory dict, not the DB."""
    import app.api.admin_settings as admin_settings_module

    store: dict[str, object] = {}

    def fake_save(session: object, overrides: dict[str, object]) -> dict[str, object]:
        validated = validate_runtime_overrides(overrides)
        store.clear()
        store.update(validated)
        return validated

    monkeypatch.setattr(admin_settings_module, "save_runtime_overrides", fake_save)

    app = create_app(settings=settings, session_factory=_unusable_session_factory)
    return TestClient(app), store


def _unusable_session_factory() -> Any:  # pragma: no cover - sessions unused in these tests
    class _Ctx:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *args: object) -> None:
            return None

    return _Ctx()


def test_admin_settings_round_trip_updates_effective_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client_with_memory_store(_settings(), monkeypatch)

    read_response = client.get("/admin/settings")
    assert read_response.status_code == 200
    payload = read_response.json()
    assert set(payload["keys"]) == set(RUNTIME_SETTING_KEYS)
    assert payload["overrides"]["openai_chat_model"] is None

    update_response = client.put(
        "/admin/settings",
        json={"overrides": {"openai_chat_model": "gpt-tuned", "openai_chat_temperature": 0.2}},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["overrides"]["openai_chat_model"] == "gpt-tuned"
    assert updated["effective"]["openai_chat_model"] == "gpt-tuned"
    assert updated["effective"]["openai_chat_temperature"] == 0.2
    assert store["openai_chat_model"] == "gpt-tuned"

    # subsequent reads see the cached overrides without re-querying the DB
    second_read = client.get("/admin/settings")
    assert second_read.json()["effective"]["openai_chat_model"] == "gpt-tuned"


def test_admin_settings_rejects_unknown_keys_and_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client_with_memory_store(_settings(), monkeypatch)

    unknown = client.put("/admin/settings", json={"overrides": {"bogus": 1}})
    assert unknown.status_code == 422
    assert "bogus" in unknown.json()["detail"]

    invalid = client.put(
        "/admin/settings",
        json={"overrides": {"openai_chat_temperature": 99}},
    )
    assert invalid.status_code == 422


def test_admin_settings_requires_admin_key_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client_with_memory_store(_settings(admin_api_key="secret-key"), monkeypatch)

    denied = client.get("/admin/settings")
    assert denied.status_code == 401

    allowed = client.get("/admin/settings", headers={"X-KB-Admin-Key": "secret-key"})
    assert allowed.status_code == 200
