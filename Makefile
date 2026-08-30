.PHONY: setup infra-up infra-down frontend-dev backend-dev ingestion-help retrieval-help db-test test lint build validate

setup:
	npm --prefix frontend ci
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e "./backend[dev]"
	.venv/bin/pip install -e "./ingestion[dev]"
	.venv/bin/pip install -e "./retrieval[dev]"

infra-up:
	docker compose up -d --wait

infra-down:
	docker compose down

frontend-dev:
	npm --prefix frontend run dev

backend-dev:
	.venv/bin/uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000

ingestion-help:
	.venv/bin/python -m beken_ingestion --help

retrieval-help:
	.venv/bin/python -m beken_retrieval --help

db-test:
	docker compose up -d --wait postgres
	BEKEN_RUN_DB_TESTS=1 .venv/bin/pytest ingestion/tests/test_database_integration.py retrieval/tests/test_postgres_integration.py

test:
	.venv/bin/pytest backend/tests ingestion/tests retrieval/tests

lint:
	npm --prefix frontend run lint
	.venv/bin/ruff check backend ingestion retrieval

build:
	npm --prefix frontend run build

validate: lint test build
	docker compose config --quiet
