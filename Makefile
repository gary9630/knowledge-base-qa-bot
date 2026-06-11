ifneq (,$(wildcard .env))
include .env
endif
export OPENAI_API_KEY
export KB_POSTGRES_PORT

UV := uv run --python 3.12
COMPOSE ?= docker compose
API_URL ?= http://localhost:8000
KB_ADMIN_API_KEY ?= local-admin-key
KB_ADMIN_API_KEY := $(or $(KB_ADMIN_API_KEY),local-admin-key)
KB_TEST_DATABASE_URL ?= postgresql+psycopg://kb:kb@postgres:5432/kb_test
BACKUP_DIR ?= backups/$(shell date -u +%Y%m%dT%H%M%SZ)
BACKUP_DB_FILE ?= $(BACKUP_DIR)/postgres.dump
BACKUP_FILES_FILE ?= $(BACKUP_DIR)/runtime-files.tar.gz
RESTORE_DB_FILE ?= $(BACKUP_DB_FILE)
RESTORE_FILES_FILE ?= $(BACKUP_FILES_FILE)
REAL_CONTENT_SOURCE_DIR ?= course-materials-md
REAL_CONTENT_CASES ?= ops/real-content-acceptance-cases.json
REAL_CONTENT_REPORT ?= tmp/real-content-acceptance-report.json
REAL_CONTENT_BACKUP_DIR ?= backups/real-content-$(shell date -u +%Y%m%dT%H%M%SZ)
REAL_CONTENT_EMBEDDING_PROVIDER ?= openai
REAL_CONTENT_EMBEDDING_MODEL ?= text-embedding-3-small
REAL_CONTENT_EMBEDDING_DIMENSION ?= 768
REAL_CONTENT_ANSWER_PROVIDER ?= fake
REAL_CONTENT_COMPOSE_PROJECT ?= kb-real-content
REAL_CONTENT_COMPOSE ?= $(COMPOSE) -p $(REAL_CONTENT_COMPOSE_PROJECT)
REAL_CONTENT_COMPOSE_ENV := KB_EMBEDDING_PROVIDER=$(REAL_CONTENT_EMBEDDING_PROVIDER) KB_OPENAI_EMBEDDING_MODEL=$(REAL_CONTENT_EMBEDDING_MODEL) KB_EMBEDDING_DIMENSION=$(REAL_CONTENT_EMBEDDING_DIMENSION) KB_ANSWER_PROVIDER=$(REAL_CONTENT_ANSWER_PROVIDER)

.PHONY: backup backup-db backup-files deploy-check deploy-check-ci dev test test-unit test-integration test-e2e lint format migrate index worker worker-once worker-status eval-seed eval-run eval-generate ops-check docker-build docker-up docker-down docker-logs docker-test docker-smoke restore-db restore-files real-content-env-check real-content-prepare real-content-index real-content-acceptance real-content-package graph-seed

backup: backup-db backup-files

backup-db:
	mkdir -p "$(BACKUP_DIR)"
	$(COMPOSE) exec -T postgres sh -c 'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --format=custom' > "$(BACKUP_DB_FILE)"

backup-files:
	mkdir -p "$(BACKUP_DIR)"
	$(COMPOSE) run --rm --no-deps --entrypoint sh app -c 'tar -czf - -C /app docs raw .kb' > "$(BACKUP_FILES_FILE)"

restore-db:
	@test "$(CONFIRM_RESTORE)" = "yes" || (echo "Set CONFIRM_RESTORE=yes to restore the database."; exit 1)
	@test -f "$(RESTORE_DB_FILE)" || (echo "Missing RESTORE_DB_FILE=$(RESTORE_DB_FILE)"; exit 1)
	$(COMPOSE) exec -T postgres sh -c 'pg_restore --clean --if-exists -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < "$(RESTORE_DB_FILE)"

restore-files:
	@test "$(CONFIRM_RESTORE)" = "yes" || (echo "Set CONFIRM_RESTORE=yes to restore runtime files."; exit 1)
	@test -f "$(RESTORE_FILES_FILE)" || (echo "Missing RESTORE_FILES_FILE=$(RESTORE_FILES_FILE)"; exit 1)
	$(COMPOSE) run --rm --no-deps --entrypoint sh app -c 'tar -xzf - -C /app' < "$(RESTORE_FILES_FILE)"

real-content-env-check:
	@test "$(REAL_CONTENT_EMBEDDING_DIMENSION)" = "768" || (echo "REAL_CONTENT_EMBEDDING_DIMENSION must be 768 for the current pgvector schema."; exit 1)
	@test "$(REAL_CONTENT_EMBEDDING_PROVIDER)" != "openai" || test -n "$$OPENAI_API_KEY" || (echo "OPENAI_API_KEY is required when REAL_CONTENT_EMBEDDING_PROVIDER=openai."; exit 1)

real-content-prepare:
	@test -d "$(REAL_CONTENT_SOURCE_DIR)" || (echo "Missing REAL_CONTENT_SOURCE_DIR=$(REAL_CONTENT_SOURCE_DIR)"; exit 1)
	$(REAL_CONTENT_COMPOSE) build app
	$(REAL_CONTENT_COMPOSE) run --rm --no-deps --volume "$(CURDIR)/$(REAL_CONTENT_SOURCE_DIR):/real-content:ro" app python -m scripts.prepare_real_content --source-dir /real-content --docs-dir /app/docs

real-content-index: real-content-env-check
	$(REAL_CONTENT_COMPOSE_ENV) $(REAL_CONTENT_COMPOSE) build app
	$(REAL_CONTENT_COMPOSE_ENV) $(REAL_CONTENT_COMPOSE) up -d postgres
	$(REAL_CONTENT_COMPOSE_ENV) $(REAL_CONTENT_COMPOSE) run --rm migrate
	$(REAL_CONTENT_COMPOSE_ENV) $(REAL_CONTENT_COMPOSE) run --rm --no-deps app python -m scripts.rebuild_index --docs-dir /app/docs --kb-dir /app/.kb

real-content-acceptance: real-content-env-check
	mkdir -p "$(dir $(REAL_CONTENT_REPORT))"
	$(REAL_CONTENT_COMPOSE_ENV) $(REAL_CONTENT_COMPOSE) build app
	$(REAL_CONTENT_COMPOSE_ENV) $(REAL_CONTENT_COMPOSE) up -d postgres
	$(REAL_CONTENT_COMPOSE_ENV) $(REAL_CONTENT_COMPOSE) run --rm --no-deps app python -m scripts.real_content_acceptance --cases /app/$(REAL_CONTENT_CASES) > "$(REAL_CONTENT_REPORT)"
	@cat "$(REAL_CONTENT_REPORT)"

real-content-package: real-content-prepare real-content-index real-content-acceptance
	$(MAKE) backup COMPOSE="$(REAL_CONTENT_COMPOSE)" BACKUP_DIR="$(REAL_CONTENT_BACKUP_DIR)" BACKUP_DB_FILE="$(REAL_CONTENT_BACKUP_DIR)/postgres.dump" BACKUP_FILES_FILE="$(REAL_CONTENT_BACKUP_DIR)/runtime-files.tar.gz"
	cp "$(REAL_CONTENT_REPORT)" "$(REAL_CONTENT_BACKUP_DIR)/real-content-acceptance-report.json"

deploy-check:
	$(UV) python -m scripts.validate_deploy_env

deploy-check-ci:
	KB_APP_ENV=production \
	KB_AUTH_SECRET_KEY=ci-auth-secret-000000000000000000 \
	KB_PLATFORM_USERNAME=ci-learner \
	KB_PLATFORM_PASSWORD=ci-platform-password \
	KB_ADMIN_API_KEY=ci-admin-api-key \
	KB_DATABASE_URL=postgresql+psycopg://kb:kb@postgres:5432/kb \
	KB_DOCS_DIR=/app/docs \
	KB_RAW_DIR=/app/raw \
	KB_KB_DIR=/app/.kb \
	KB_EMBEDDING_PROVIDER=openai \
	KB_ANSWER_PROVIDER=openai \
	KB_EMBEDDING_DIMENSION=768 \
	OPENAI_API_KEY=sk-ci-placeholder \
	$(UV) python -m scripts.validate_deploy_env

dev:
	$(UV) uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	$(UV) pytest

test-unit:
	$(UV) pytest tests/unit

test-integration:
	$(UV) pytest tests/integration

test-e2e:
	$(UV) pytest tests/e2e

lint:
	$(UV) ruff check .
	$(UV) mypy .

format:
	$(UV) ruff format .
	$(UV) ruff check . --fix

migrate:
	$(UV) alembic upgrade head

index:
	curl -fsS -X POST "$(API_URL)/index"

worker-once:
	$(UV) python -m scripts.run_background_worker --once

worker:
	$(UV) python -m scripts.run_background_worker

worker-status:
	curl -fsS -H "X-KB-Admin-Key: $(KB_ADMIN_API_KEY)" "$(API_URL)/admin/jobs/runtime"

graph-seed:
	$(UV) python -m scripts.seed_concept_graph --file docs/plans/2026-06-11-concept-graph-seed.json

eval-seed:
	$(UV) python -m scripts.seed_eval_cases

eval-run:
	$(UV) python -m scripts.run_evals --trigger scheduled

eval-generate:
	$(UV) python -m scripts.generate_eval_cases

ops-check:
	@echo "health:"
	curl -fsS "$(API_URL)/health"
	@echo
	@echo "ready:"
	curl -fsS "$(API_URL)/ready"
	@echo
	@echo "metrics:"
	curl -fsS -H "X-KB-Admin-Key: $(KB_ADMIN_API_KEY)" "$(API_URL)/metrics"
	@echo
	@echo "worker runtime:"
	curl -fsS -H "X-KB-Admin-Key: $(KB_ADMIN_API_KEY)" "$(API_URL)/admin/jobs/runtime"
	@echo

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up --build app

docker-down:
	$(COMPOSE) --profile worker down

docker-logs:
	$(COMPOSE) logs -f app postgres

docker-test:
	$(COMPOSE) up -d postgres
	$(COMPOSE) exec postgres sh -c 'until pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"; do sleep 1; done'
	$(COMPOSE) exec postgres sh -c 'set -eu; DB_EXISTS=$$(psql -U "$$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '\''kb_test'\''"); if [ "$$DB_EXISTS" != "1" ]; then createdb -U "$$POSTGRES_USER" kb_test; fi'
	$(COMPOSE) build test
	$(COMPOSE) run --rm -e KB_DATABASE_URL_TEST=$(KB_TEST_DATABASE_URL) test pytest

docker-smoke:
	$(COMPOSE) --profile worker up --build -d app worker
	@for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		if curl -fsS "$(API_URL)/health" >/dev/null; then exit 0; fi; \
		sleep 2; \
	done; \
	echo "App did not become healthy at $(API_URL)"; \
	exit 1
	KB_DOCKER_E2E=1 KB_ADMIN_API_KEY=$(KB_ADMIN_API_KEY) $(UV) pytest tests/e2e/test_docker_compose.py
