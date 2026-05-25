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


def test_compose_defines_app_postgres_and_worker_contracts() -> None:
    compose = read_project_file("docker-compose.yml")

    assert re.search(r"^\s+app:\s*$", compose, re.MULTILINE)
    assert re.search(r"^\s+postgres:\s*$", compose, re.MULTILINE)
    assert re.search(r"^\s+worker:\s*$", compose, re.MULTILINE)
    assert re.search(r"^\s+migrate:\s*$", compose, re.MULTILINE)
    assert "pgvector/pgvector" in compose
    assert '"${KB_POSTGRES_PORT:-5432}:5432"' in compose
    assert "KB_DATABASE_URL=postgresql+psycopg://kb:kb@postgres:5432/kb" in compose
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
    assert "SELECT 1 FROM pg_database" in makefile


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
