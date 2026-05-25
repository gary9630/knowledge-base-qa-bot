from pathlib import Path

import pytest

from app.core.config import Settings
from app.main import create_app

_SETTINGS_ENV_KEYS = (
    "KB_DOCS_DIR",
    "OPENAI_API_KEY",
    "KB_OPENAI_API_KEY",
    "KB_OPENAI_EMBEDDING_MODEL",
    "KB_OPENAI_CHAT_MODEL",
    "KB_ADMIN_API_KEY",
    "KB_MAX_UPLOAD_BYTES",
)


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in _SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_default_paths_are_product_defaults() -> None:
    settings = Settings()

    assert settings.docs_dir == "docs"
    assert settings.raw_dir == "raw"
    assert settings.kb_dir == ".kb"
    assert settings.default_retrieval_strategy == "hybrid"


def test_settings_support_fake_providers_for_tests() -> None:
    settings = Settings(embedding_provider="fake", answer_provider="fake")

    assert settings.embedding_provider == "fake"
    assert settings.answer_provider == "fake"


def test_settings_docs_dir_can_be_overridden_by_prefixed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KB_DOCS_DIR", "knowledge-docs")

    settings = Settings()

    assert settings.docs_dir == "knowledge-docs"


def test_settings_openai_api_key_uses_unprefixed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("KB_OPENAI_API_KEY", raising=False)

    settings = Settings()

    assert settings.openai_api_key == "test-key"


def test_settings_openai_api_key_ignores_prefixed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("KB_OPENAI_API_KEY", "prefixed-key")

    settings = Settings()

    assert settings.openai_api_key is None


def test_settings_blank_optional_env_values_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("KB_OPENAI_EMBEDDING_MODEL", "")
    monkeypatch.setenv("KB_OPENAI_CHAT_MODEL", "")

    settings = Settings()

    assert settings.openai_api_key is None
    assert settings.openai_embedding_model is None
    assert settings.openai_chat_model is None


def test_settings_openai_api_key_can_be_set_by_constructor() -> None:
    settings = Settings(openai_api_key="constructor-key")

    assert settings.openai_api_key == "constructor-key"


def test_app_rejects_embedding_dimension_that_does_not_match_schema() -> None:
    settings = Settings(embedding_dimension=768)

    with pytest.raises(ValueError, match="embedding_dimension must match database schema"):
        create_app(settings=settings)
