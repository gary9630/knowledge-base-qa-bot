UV := uv run --python 3.12
COMPOSE ?= docker compose
API_URL ?= http://localhost:8000
KB_ADMIN_API_KEY ?= local-admin-key
KB_TEST_DATABASE_URL ?= postgresql+psycopg://kb:kb@postgres:5432/kb_test

.PHONY: dev test test-unit test-integration test-e2e lint format migrate index eval-seed eval-run ops-check docker-build docker-up docker-down docker-logs docker-test

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

eval-seed:
	$(UV) python -m scripts.seed_eval_cases

eval-run:
	$(UV) python -m scripts.run_evals --trigger scheduled

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

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up --build app

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f app postgres

docker-test:
	$(COMPOSE) up -d postgres
	$(COMPOSE) exec postgres sh -c 'until pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"; do sleep 1; done'
	$(COMPOSE) exec postgres sh -c 'set -eu; DB_EXISTS=$$(psql -U "$$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '\''kb_test'\''"); if [ "$$DB_EXISTS" != "1" ]; then createdb -U "$$POSTGRES_USER" kb_test; fi'
	$(COMPOSE) build test
	$(COMPOSE) run --rm -e KB_DATABASE_URL_TEST=$(KB_TEST_DATABASE_URL) test pytest
