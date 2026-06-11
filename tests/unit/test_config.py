from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app

_SETTINGS_ENV_KEYS = (
    "KB_DOCS_DIR",
    "OPENAI_API_KEY",
    "KB_OPENAI_API_KEY",
    "KB_OPENAI_EMBEDDING_MODEL",
    "KB_OPENAI_CHAT_MODEL",
    "KB_OPENAI_REQUEST_TIMEOUT_SECONDS",
    "KB_OPENAI_MAX_RETRIES",
    "KB_OPENAI_CHAT_MAX_COMPLETION_TOKENS",
    "KB_PROVIDER_BUDGET_ENABLED",
    "KB_PROVIDER_BUDGET_DAILY_TOKEN_LIMIT",
    "KB_PROVIDER_BUDGET_DAILY_CALL_LIMIT",
    "KB_PROVIDER_BUDGET_ERROR_RATE_LIMIT",
    "KB_PROVIDER_BUDGET_WARNING_RATIO",
    "KB_PROVIDER_BUDGET_BLOCK_ON_EXCEEDED",
    "KB_PLATFORM_COHORTS",
    "KB_PLATFORM_EXTRA_VISIBILITY_LABELS",
    "KB_ADMIN_API_KEY",
    "KB_MAX_UPLOAD_BYTES",
    "KB_RATE_LIMIT_ENABLED",
    "KB_RATE_LIMIT_WINDOW_SECONDS",
    "KB_RATE_LIMIT_LOGIN_REQUESTS",
    "KB_RATE_LIMIT_CHAT_REQUESTS",
    "KB_RATE_LIMIT_ADMIN_REQUESTS",
    "KB_RATE_LIMIT_UPLOAD_REQUESTS",
    "KB_MAX_CONCURRENT_UPLOADS",
    "KB_BACKGROUND_JOB_STALE_AFTER_SECONDS",
    "KB_BACKGROUND_JOB_RETRY_BASE_DELAY_SECONDS",
    "KB_BACKGROUND_JOB_RETRY_MAX_DELAY_SECONDS",
    "KB_EMBEDDING_DIMENSION",
    "KB_TOKEN_ENCODING",
    "KB_CONTEXT_NEIGHBOR_SECTIONS",
    "KB_CONTEXT_TOKEN_BUDGET",
    "KB_GRAPH_EXTRACTION_ENABLED",
    "KB_GRAPH_MAX_CONCEPTS_PER_DOC",
    "KB_GRAPH_EXTRACTION_TOKEN_BUDGET",
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


def test_settings_default_embedding_dimension_matches_schema() -> None:
    settings = Settings()

    assert settings.embedding_dimension == 768


def test_settings_rate_limit_defaults_are_production_safe() -> None:
    settings = Settings()

    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_window_seconds == 60
    assert settings.rate_limit_login_requests == 10
    assert settings.rate_limit_chat_requests == 60
    assert settings.rate_limit_admin_requests == 60
    assert settings.rate_limit_upload_requests == 10
    assert settings.max_concurrent_uploads == 2


def test_settings_rate_limit_values_can_be_overridden_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KB_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("KB_RATE_LIMIT_WINDOW_SECONDS", "30")
    monkeypatch.setenv("KB_RATE_LIMIT_LOGIN_REQUESTS", "3")
    monkeypatch.setenv("KB_RATE_LIMIT_CHAT_REQUESTS", "7")
    monkeypatch.setenv("KB_RATE_LIMIT_ADMIN_REQUESTS", "11")
    monkeypatch.setenv("KB_RATE_LIMIT_UPLOAD_REQUESTS", "2")
    monkeypatch.setenv("KB_MAX_CONCURRENT_UPLOADS", "1")

    settings = Settings()

    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_window_seconds == 30
    assert settings.rate_limit_login_requests == 3
    assert settings.rate_limit_chat_requests == 7
    assert settings.rate_limit_admin_requests == 11
    assert settings.rate_limit_upload_requests == 2
    assert settings.max_concurrent_uploads == 1


def test_settings_background_job_reliability_defaults_are_production_safe() -> None:
    settings = Settings()

    assert settings.background_job_stale_after_seconds == 3600
    assert settings.background_job_retry_base_delay_seconds == 30
    assert settings.background_job_retry_max_delay_seconds == 300


def test_settings_background_job_reliability_values_can_be_overridden_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KB_BACKGROUND_JOB_STALE_AFTER_SECONDS", "120")
    monkeypatch.setenv("KB_BACKGROUND_JOB_RETRY_BASE_DELAY_SECONDS", "5")
    monkeypatch.setenv("KB_BACKGROUND_JOB_RETRY_MAX_DELAY_SECONDS", "60")

    settings = Settings()

    assert settings.background_job_stale_after_seconds == 120
    assert settings.background_job_retry_base_delay_seconds == 5
    assert settings.background_job_retry_max_delay_seconds == 60


def test_settings_source_access_values_can_be_overridden_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KB_PLATFORM_COHORTS", "spring-2026, alumni")
    monkeypatch.setenv("KB_PLATFORM_EXTRA_VISIBILITY_LABELS", "staff beta")

    settings = Settings()

    assert settings.platform_cohorts == "spring-2026, alumni"
    assert settings.platform_extra_visibility_labels == "staff beta"


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


def test_settings_openai_reliability_defaults_are_production_safe() -> None:
    settings = Settings()

    assert settings.openai_request_timeout_seconds == 30.0
    assert settings.openai_max_retries == 2
    assert settings.openai_chat_max_completion_tokens == 1024


def test_settings_openai_reliability_values_can_be_overridden_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KB_OPENAI_REQUEST_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("KB_OPENAI_MAX_RETRIES", "4")
    monkeypatch.setenv("KB_OPENAI_CHAT_MAX_COMPLETION_TOKENS", "321")

    settings = Settings()

    assert settings.openai_request_timeout_seconds == 12.5
    assert settings.openai_max_retries == 4
    assert settings.openai_chat_max_completion_tokens == 321


def test_settings_provider_budget_defaults_are_non_disruptive() -> None:
    settings = Settings()

    assert settings.provider_budget_enabled is True
    assert settings.provider_budget_daily_token_limit == 0
    assert settings.provider_budget_daily_call_limit == 0
    assert settings.provider_budget_error_rate_limit == 0.0
    assert settings.provider_budget_warning_ratio == 0.8
    assert settings.provider_budget_block_on_exceeded is False


def test_settings_provider_budget_values_can_be_overridden_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KB_PROVIDER_BUDGET_ENABLED", "false")
    monkeypatch.setenv("KB_PROVIDER_BUDGET_DAILY_TOKEN_LIMIT", "10000")
    monkeypatch.setenv("KB_PROVIDER_BUDGET_DAILY_CALL_LIMIT", "50")
    monkeypatch.setenv("KB_PROVIDER_BUDGET_ERROR_RATE_LIMIT", "0.25")
    monkeypatch.setenv("KB_PROVIDER_BUDGET_WARNING_RATIO", "0.7")
    monkeypatch.setenv("KB_PROVIDER_BUDGET_BLOCK_ON_EXCEEDED", "true")

    settings = Settings()

    assert settings.provider_budget_enabled is False
    assert settings.provider_budget_daily_token_limit == 10000
    assert settings.provider_budget_daily_call_limit == 50
    assert settings.provider_budget_error_rate_limit == 0.25
    assert settings.provider_budget_warning_ratio == 0.7
    assert settings.provider_budget_block_on_exceeded is True


def test_settings_openai_api_key_can_be_set_by_constructor() -> None:
    settings = Settings(openai_api_key="constructor-key")

    assert settings.openai_api_key == "constructor-key"


def test_app_rejects_embedding_dimension_that_does_not_match_schema() -> None:
    settings = Settings(embedding_dimension=1536)

    with pytest.raises(
        ValueError,
        match="embedding_dimension must match database schema \\(768\\)",
    ):
        create_app(settings=settings)


def test_context_expansion_defaults() -> None:
    settings = Settings()
    assert settings.token_encoding == "o200k_base"
    assert settings.context_neighbor_sections == 1
    assert settings.context_token_budget == 8000


def test_token_encoding_rejects_unknown_encoding() -> None:
    with pytest.raises(ValidationError, match="token_encoding"):
        Settings(token_encoding="not-a-real-encoding")


def test_context_token_budget_enforces_floor() -> None:
    with pytest.raises(ValidationError, match="context_token_budget"):
        Settings(context_token_budget=500)


def test_context_neighbor_sections_rejects_negative() -> None:
    with pytest.raises(ValidationError, match="context_neighbor_sections"):
        Settings(context_neighbor_sections=-1)


def test_graph_extraction_defaults() -> None:
    settings = Settings()
    assert settings.graph_extraction_enabled is True
    assert settings.graph_max_concepts_per_doc == 30
    assert settings.graph_extraction_token_budget == 12000


def test_graph_settings_validation() -> None:
    with pytest.raises(ValidationError, match="graph_max_concepts_per_doc"):
        Settings(graph_max_concepts_per_doc=0)
    with pytest.raises(ValidationError, match="graph_extraction_token_budget"):
        Settings(graph_extraction_token_budget=500)
