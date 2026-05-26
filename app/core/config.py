from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    platform_session_ttl_seconds: int = 86_400
    admin_api_key: str | None = None
    max_upload_bytes: int = 10_000_000
    embedding_provider: str = "fake"
    answer_provider: str = "fake"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    openai_embedding_model: str | None = None
    openai_chat_model: str | None = None
    embedding_dimension: int = 1536
