from scripts.validate_deploy_env import collect_deploy_env_errors


def valid_env() -> dict[str, str]:
    return {
        "KB_APP_ENV": "production",
        "KB_AUTH_SECRET_KEY": "x" * 32,
        "KB_PLATFORM_USERNAME": "course-user",
        "KB_PLATFORM_PASSWORD": "course-password-123",
        "KB_ADMIN_API_KEY": "admin-key-123456789",
        "KB_DATABASE_URL": "postgresql+psycopg://kb:kb@postgres:5432/kb",
        "KB_DOCS_DIR": "/app/docs",
        "KB_RAW_DIR": "/app/raw",
        "KB_KB_DIR": "/app/.kb",
        "KB_EMBEDDING_PROVIDER": "openai",
        "KB_ANSWER_PROVIDER": "openai",
        "KB_EMBEDDING_DIMENSION": "1536",
        "OPENAI_API_KEY": "sk-ci-placeholder",
    }


def test_deploy_env_validation_accepts_production_ready_settings() -> None:
    assert collect_deploy_env_errors(valid_env()) == []


def test_deploy_env_validation_rejects_missing_and_development_defaults() -> None:
    env = valid_env()
    env["KB_AUTH_SECRET_KEY"] = "short"
    env["KB_PLATFORM_USERNAME"] = "student"
    env["KB_PLATFORM_PASSWORD"] = "student-password"
    env["KB_ADMIN_API_KEY"] = "local-admin-key"
    env["KB_ANSWER_PROVIDER"] = "openai"
    env.pop("OPENAI_API_KEY")

    errors = collect_deploy_env_errors(env)

    assert any("KB_AUTH_SECRET_KEY" in error for error in errors)
    assert any("KB_PLATFORM_USERNAME" in error for error in errors)
    assert any("KB_PLATFORM_PASSWORD" in error for error in errors)
    assert any("KB_ADMIN_API_KEY" in error for error in errors)
    assert any("OPENAI_API_KEY" in error for error in errors)


def test_deploy_env_validation_rejects_fake_providers_by_default() -> None:
    env = valid_env()
    env["KB_EMBEDDING_PROVIDER"] = "fake"

    assert any("KB_EMBEDDING_PROVIDER" in error for error in collect_deploy_env_errors(env))
    assert collect_deploy_env_errors(env, allow_fake_providers=True) == []
