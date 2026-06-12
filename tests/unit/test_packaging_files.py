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
    for path in (
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "Makefile",
        ".dockerignore",
        ".github/workflows/deploy.yml",
        "scripts/deploy_production.sh",
        "scripts/scp_knowledge_files_to_server.sh",
        "ops/nginx/kb.conf.example",
    ):
        assert (ROOT / path).is_file(), f"{path} should exist for deploy packaging"


def test_ci_workflow_runs_lint_tests_and_docker_checks() -> None:
    workflow = read_project_file(".github/workflows/ci.yml")

    assert "python-version: \"3.12\"" in workflow
    assert "uv sync --python 3.12 --group dev" in workflow
    assert "make lint" in workflow
    assert "make test" in workflow
    assert "make deploy-check-ci" in workflow
    assert "docker compose --profile worker --profile test config" in workflow
    assert "make docker-test" in workflow
    assert "make docker-smoke" in workflow


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
    assert (
        "KB_DATABASE_URL=${KB_DATABASE_URL:-postgresql+psycopg://kb:kb@postgres:5432/kb}"
        in compose
    )
    assert "POSTGRES_PASSWORD: ${KB_POSTGRES_PASSWORD:-kb}" in compose
    assert "KB_ADMIN_API_KEY=${KB_ADMIN_API_KEY:-local-admin-key}" in compose
    assert compose.count("alembic upgrade head") == 1
    assert "uvicorn app.main:app" in compose
    assert "python -m scripts.run_background_worker" in compose
    assert "KB_WORKER_ID=${KB_WORKER_ID:-compose-worker}" in compose
    assert "KB_WORKER_HEARTBEAT_INTERVAL_SECONDS" in compose
    assert "restart: unless-stopped" in compose
    assert re.search(r"depends_on:\s*\n\s+postgres:", compose)
    assert "./docs:/app/docs" not in compose
    assert "./raw:/app/raw" not in compose
    assert "source: docs_data" in compose
    assert "target: /app/docs" in compose
    assert "source: raw_data" in compose
    assert "target: /app/raw" in compose
    assert "nocopy: true" not in compose


def test_production_compose_override_uses_loaded_image_and_loopback_ports() -> None:
    compose = read_project_file("docker-compose.prod.yml")

    assert "image: ${KB_IMAGE:" in compose
    assert "pull_policy: never" in compose
    assert "restart: unless-stopped" in compose
    assert "${KB_POSTGRES_PORT:-127.0.0.1:5432}:5432" in compose
    assert "${KB_APP_PORT:-127.0.0.1:8000}:8000" in compose
    assert "POSTGRES_PASSWORD: ${KB_POSTGRES_PASSWORD:" in compose
    assert "KB_DATABASE_URL: ${KB_DATABASE_URL:" in compose


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
        "backup",
        "backup-db",
        "backup-files",
        "dev",
        "test",
        "test-unit",
        "test-integration",
        "test-e2e",
        "lint",
        "format",
        "migrate",
        "index",
        "deploy-check",
        "deploy-check-ci",
        "worker-once",
        "worker",
        "worker-status",
        "ops-check",
        "docker-build",
        "docker-up",
        "docker-test",
        "docker-smoke",
        "restore-db",
        "restore-files",
        "real-content-prepare",
        "real-content-index",
        "real-content-acceptance",
        "real-content-package",
    )

    for target in expected_targets:
        assert re.search(rf"^{target}:", makefile, re.MULTILINE), f"missing {target} target"

    assert "uv run --python 3.12" in makefile
    assert "docker compose" in makefile
    assert "include .env" in makefile
    assert "export OPENAI_API_KEY" in makefile
    assert "export KB_POSTGRES_PORT" in makefile
    assert ".EXPORT_ALL_VARIABLES:" not in makefile
    assert "|| true" not in makefile
    assert "pg_isready" in makefile
    assert "$(API_URL)/ready" in makefile
    assert "$(API_URL)/metrics" in makefile
    assert "python -m scripts.run_background_worker --once" in makefile
    assert "python -m scripts.run_background_worker" in makefile
    assert "python -m scripts.validate_deploy_env" in makefile
    assert "$(API_URL)/admin/jobs/runtime" in makefile
    assert "KB_DOCKER_E2E=1" in makefile
    assert "tests/e2e/test_docker_compose.py" in makefile
    assert "$(COMPOSE) --profile worker down" in makefile
    assert "KB_ADMIN_API_KEY" in makefile
    assert "X-KB-Admin-Key" in makefile
    assert "SELECT 1 FROM pg_database" in makefile
    docker_test_body = makefile.split("docker-test:", 1)[1]
    assert "$(COMPOSE) build test" in docker_test_body
    assert "pg_dump" in makefile
    assert "pg_restore" in makefile
    assert "CONFIRM_RESTORE=yes" in makefile
    assert "REAL_CONTENT_SOURCE_DIR" in makefile
    assert "REAL_CONTENT_COMPOSE_PROJECT" in makefile
    assert "course-materials-md" in makefile
    assert "python -m scripts.prepare_real_content" in makefile
    assert "python -m scripts.rebuild_index" in makefile
    assert "python -m scripts.real_content_acceptance" in makefile
    assert 'test -n "$$OPENAI_API_KEY"' in makefile
    assert "REAL_CONTENT_SOURCE_PATH" in makefile
    assert 'BACKUP_DB_FILE="$(REAL_CONTENT_BACKUP_DIR)/postgres.dump"' in makefile
    assert (
        'BACKUP_FILES_FILE="$(REAL_CONTENT_BACKUP_DIR)/runtime-files.tar.gz"'
        in makefile
    )


def test_backup_restore_runbook_documents_database_and_file_restore() -> None:
    runbook = read_project_file("ops/backup-restore.md")

    assert "pg_dump" in runbook
    assert "pg_restore" in runbook
    assert "docs_data" in runbook
    assert "raw_data" in runbook
    assert "kb_data" in runbook
    assert "make ops-check" in runbook
    assert "CONFIRM_RESTORE=yes" in runbook
    assert "real-content-package" in runbook
    assert "postgres.dump" in runbook
    assert "runtime-files.tar.gz" in runbook
    assert "ops/live-answer-acceptance.md" in runbook
    assert "gpt-5.4-mini" in runbook


def test_production_deploy_runbook_documents_release_sequence() -> None:
    runbook = read_project_file("ops/deploy.md")

    assert "ops/env.production.example" in runbook
    assert "KB_AUTH_SECRET_KEY" in runbook
    assert "KB_ADMIN_API_KEY" in runbook
    assert "make deploy-check" in runbook
    assert "make docker-smoke" in runbook
    assert "make backup" in runbook
    assert "make migrate" in runbook
    assert "make ops-check" in runbook
    assert "docker compose" in runbook
    assert "rollback" in runbook.lower()
    assert "course-materials-md" in runbook
    assert "make real-content-package" in runbook
    assert "ops/live-answer-acceptance.md" in runbook
    assert "KB_POSTGRES_PORT=55432" in runbook
    assert "docker-compose.prod.yml" in runbook
    assert "docker save" in runbook
    assert "docker load" in runbook
    assert ".github/workflows/deploy.yml" in runbook
    assert "scripts/scp_knowledge_files_to_server.sh" in runbook


def test_deploy_workflow_copies_image_archive_and_runs_remote_deploy() -> None:
    workflow = read_project_file(".github/workflows/deploy.yml")

    assert "name: Deploy Production" in workflow
    assert "workflow_run:" in workflow
    assert "workflows: [\"CI\"]" in workflow
    assert "branches: [main]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "environment: production" in workflow
    assert "digitalocean/action-doctl@v2" not in workflow
    assert "doctl registry login" not in workflow
    assert "DOCR_REGISTRY" not in workflow
    assert "DIGITALOCEAN_ACCESS_TOKEN" not in workflow
    assert "registry.digitalocean.com" not in workflow
    assert "docker push" not in workflow
    assert "docker save" in workflow
    assert "gzip" in workflow
    assert "scp " in workflow
    assert "KB_IMAGE_ARCHIVE" in workflow
    assert "DEPLOY_SSH_PRIVATE_KEY" in workflow
    assert "DEPLOY_SSH_KNOWN_HOSTS" in workflow
    assert "scripts/deploy_production.sh" in workflow
    assert "--force" not in workflow


def test_remote_deploy_script_uses_production_compose_without_rebuilding() -> None:
    script = read_project_file("scripts/deploy_production.sh")

    assert "set -Eeuo pipefail" in script
    assert "/etc/kb/production.env" in script
    assert "docker-compose.prod.yml" in script
    assert "requested_kb_image" in script
    assert "KB_IMAGE_ARCHIVE" in script
    assert "docker load" in script
    assert "${KB_IMAGE:?" in script
    assert "docker compose" in script
    assert "pull app migrate worker eval-runner" not in script
    assert "Skipping image pull" in script
    assert "run --rm migrate" in script
    assert "up -d --no-build app" in script
    assert "--profile worker up -d --no-build worker" in script
    assert "/ready" in script
    assert "/admin/jobs/runtime" in script
    assert "git checkout --force" not in script


def test_knowledge_upload_script_uses_connect_server_and_versioned_remote_directory() -> None:
    script = read_project_file("scripts/scp_knowledge_files_to_server.sh")

    assert "connect-server.sh" in script
    assert "course-materials-md" in script
    assert "REMOTE_UPLOAD_ROOT" in script
    assert "knowledge-uploads" in script
    assert "scp" in script
    assert "tar -xzf" in script
    assert "REAL_CONTENT_SOURCE_DIR" in script
    assert "rm -rf" not in script


def test_live_answer_acceptance_runbook_documents_required_cases() -> None:
    runbook = read_project_file("ops/live-answer-acceptance.md")

    assert "gpt-5.4-mini" in runbook
    assert "text-embedding-3-small" in runbook
    assert "KB_EMBEDDING_DIMENSION" in runbook
    assert "CAP theorem" in runbook
    assert "RAG flow" in runbook
    assert "Message queue" in runbook
    assert "/chat/stream" in runbook
    assert "answer_quality.answer_valid" in runbook
    assert "selected_source_ids" in runbook
    assert "cited_source_ids" in runbook


def test_real_content_acceptance_cases_are_documented_for_course_materials() -> None:
    cases = read_project_file("ops/real-content-acceptance-cases.json")

    assert "CAP theorem" in cases
    assert "Overload Protection" in cases
    assert "RAG" in cases
    assert "Message Queue" in cases
    assert "Database Indexing" in cases


def test_production_env_example_documents_required_deploy_settings() -> None:
    example = read_project_file("ops/env.production.example")

    for key in (
        "KB_APP_ENV=production",
        "KB_AUTH_SECRET_KEY=",
        "KB_PLATFORM_USERNAME=",
        "KB_PLATFORM_PASSWORD=",
        "KB_ADMIN_API_KEY=",
        "KB_DATABASE_URL=",
        "KB_DOCS_DIR=",
        "KB_RAW_DIR=",
        "KB_KB_DIR=",
        "KB_EMBEDDING_PROVIDER=openai",
        "KB_ANSWER_PROVIDER=openai",
        "OPENAI_API_KEY=",
    ):
        assert key in example


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
