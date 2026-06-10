from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.retrieval.dimensions import PGVECTOR_EMBEDDING_DIMENSION


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KB_",
        extra="ignore",
        env_ignore_empty=True,
    )

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://kb:kb@localhost:5432/kb"
    docs_dir: str = "docs"
    raw_dir: str = "raw"
    kb_dir: str = ".kb"
    default_retrieval_strategy: str = "hybrid"
    auth_secret_key: str | None = None
    platform_username: str | None = None
    platform_password: str | None = None
    platform_cohorts: str = ""
    platform_extra_visibility_labels: str = ""
    platform_session_ttl_seconds: int = 86_400
    admin_api_key: str | None = None
    max_upload_bytes: int = 10_000_000
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    rate_limit_login_requests: int = Field(default=10, ge=1)
    rate_limit_chat_requests: int = Field(default=60, ge=1)
    rate_limit_admin_requests: int = Field(default=60, ge=1)
    rate_limit_upload_requests: int = Field(default=10, ge=1)
    max_concurrent_uploads: int = Field(default=2, ge=1)
    background_job_stale_after_seconds: int = Field(default=3600, ge=1)
    background_job_retry_base_delay_seconds: int = Field(default=30, ge=0)
    background_job_retry_max_delay_seconds: int = Field(default=300, ge=0)
    worker_id: str | None = None
    worker_heartbeat_interval_seconds: int = Field(default=30, ge=1)
    worker_heartbeat_stale_after_seconds: int = Field(default=120, ge=1)
    embedding_provider: str = "fake"
    answer_provider: str = "fake"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    openai_embedding_model: str | None = None
    openai_chat_model: str | None = None
    openai_request_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_max_retries: int = Field(default=2, ge=0)
    openai_chat_max_completion_tokens: int = Field(default=1024, ge=1)
    provider_budget_enabled: bool = True
    provider_budget_daily_token_limit: int = Field(default=0, ge=0)
    provider_budget_daily_call_limit: int = Field(default=0, ge=0)
    provider_budget_error_rate_limit: float = Field(default=0.0, ge=0.0, le=1.0)
    provider_budget_warning_ratio: float = Field(default=0.8, ge=0.0, le=1.0)
    provider_budget_block_on_exceeded: bool = False
    embedding_dimension: int = PGVECTOR_EMBEDDING_DIMENSION
    token_encoding: str = "o200k_base"
    context_neighbor_sections: int = Field(default=1, ge=0)
    context_token_budget: int = Field(default=8000, ge=1000)

    @field_validator("token_encoding")
    @classmethod
    def _validate_token_encoding(cls, value: str) -> str:
        import tiktoken

        tiktoken.get_encoding(value)  # raises for unknown encodings (fail fast at startup)
        return value
