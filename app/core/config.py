from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="KB_", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://kb:kb@localhost:5432/kb"
    docs_dir: str = "docs"
    raw_dir: str = "raw"
    kb_dir: str = ".kb"
    default_retrieval_strategy: str = "hybrid"
    embedding_provider: str = "fake"
    answer_provider: str = "fake"
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_embedding_model: str | None = None
    openai_chat_model: str | None = None
    embedding_dimension: int = 1536
