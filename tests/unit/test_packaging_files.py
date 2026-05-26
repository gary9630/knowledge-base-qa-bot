from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def read_project_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_packaging_files_exist() -> None:
    for path in ("Dockerfile", "docker-compose.yml", "Makefile", ".dockerignore"):
        assert (ROOT / path).is_file(), f"{path} should exist for deploy packaging"


def test_dockerfile_packages_python_312_fastapi_app() -> None:
    dockerfile = read_project_file("Dockerfile")
    runtime_stage = dockerfile.split("FROM app AS test", 1)[0]

    assert re.search(r"FROM\s+python:3\.12", dockerfile)
    assert "uvicorn" in dockerfile
    assert "app.main:app" in dockerfile
    assert "uv sync --frozen --no-cache --no-dev --no-install-project" in runtime_stage
    assert "--group dev" not in runtime_stage
    assert "uv run" not in runtime_stage
    assert "EXPOSE 8000" in dockerfile


def test_dockerfile_creates_owned_runtime_directories_before_chown() -> None:
    dockerfile = read_project_file("Dockerfile")

    runtime_setup = re.search(
        r"RUN useradd .*?mkdir -p (?P<mkdir>.*?)\\\n\s+&& "
        r"chown -R appuser:appuser (?P<chown>[^\n]+)",
        dockerfile,
        re.DOTALL,
    )

    assert runtime_setup is not None
    mkdir_paths = set(runtime_setup.group("mkdir").split())
    chown_paths = set(runtime_setup.group("chown").split())

    assert chown_paths <= mkdir_paths | {"/app"}


def test_compose_defines_app_postgres_and_worker_contracts() -> None:
    compose = read_project_file("docker-compose.yml")

    assert re.search(r"^\s+app:\s*$", compose, re.MULTILINE)
    assert re.search(r"^\s+postgres:\s*$", compose, re.MULTILINE)
    assert re.search(r"^\s+worker:\s*$", compose, re.MULTILINE)
    assert re.search(r"^\s+migrate:\s*$", compose, re.MULTILINE)
    assert "pgvector/pgvector" in compose
    assert '"${KB_POSTGRES_PORT:-5432}:5432"' in compose
    assert "KB_DATABASE_URL=postgresql+psycopg://kb:kb@postgres:5432/kb" in compose
    assert "KB_ADMIN_API_KEY=${KB_ADMIN_API_KEY:-local-admin-key}" in compose
    assert compose.count("alembic upgrade head") == 1
    assert "uvicorn app.main:app" in compose
    assert re.search(r"depends_on:\s*\n\s+postgres:", compose)
    assert "./docs:/app/docs" not in compose
    assert "./raw:/app/raw" not in compose
    assert "source: docs_data" in compose
    assert "target: /app/docs" in compose
    assert "source: raw_data" in compose
    assert "target: /app/raw" in compose
    assert "nocopy: true" not in compose


def test_compose_test_profile_uses_isolated_test_environment() -> None:
    compose = read_project_file("docker-compose.yml")
    test_service = compose.split("\n  test:\n", 1)[1].split("\nvolumes:", 1)[0]

    assert "environment: *app-environment" not in test_service
    assert "KB_APP_ENV=production" not in test_service
    assert "KB_ADMIN_API_KEY" not in test_service
    assert "KB_DOCS_DIR" not in test_service
    assert "KB_RAW_DIR" not in test_service
    assert "KB_KB_DIR" not in test_service


def test_dockerignore_excludes_development_docs_from_runtime_image() -> None:
    dockerignore = read_project_file(".dockerignore")

    assert "docs/plans" in dockerignore


def test_makefile_exposes_dev_test_lint_migration_and_docker_targets() -> None:
    makefile = read_project_file("Makefile")
    expected_targets = (
        "dev",
        "test",
        "test-unit",
        "test-integration",
        "test-e2e",
        "lint",
        "format",
        "migrate",
        "index",
        "ops-check",
        "docker-build",
        "docker-up",
        "docker-test",
    )

    for target in expected_targets:
        assert re.search(rf"^{target}:", makefile, re.MULTILINE), f"missing {target} target"

    assert "uv run --python 3.12" in makefile
    assert "docker compose" in makefile
    assert "|| true" not in makefile
    assert "pg_isready" in makefile
    assert "$(API_URL)/ready" in makefile
    assert "$(API_URL)/metrics" in makefile
    assert "KB_ADMIN_API_KEY" in makefile
    assert "X-KB-Admin-Key" in makefile
    assert "SELECT 1 FROM pg_database" in makefile
    docker_test_body = makefile.split("docker-test:", 1)[1]
    assert "$(COMPOSE) build test" in docker_test_body


def test_compose_config_is_valid_when_docker_cli_is_available() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed")

    result = subprocess.run(
        ["docker", "compose", "--profile", "worker", "--profile", "test", "config"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "pgvector/pgvector:pg16" in result.stdout
    assert "migrate:" in result.stdout
