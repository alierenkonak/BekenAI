.PHONY: setup infra-up infra-down frontend-dev backend-dev worker-dev ingestion-help retrieval-help db-test test lint build validate

setup:
	npm --prefix frontend ci
	python3 -m venv .venv
	.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements/ci.lock
	.venv/bin/python -m pip install --no-deps --no-build-isolation -e "./backend[dev]" -e "./ingestion[dev]" -e "./retrieval[dev,server]"
	.venv/bin/python -m pip check

infra-up:
	docker compose up -d --wait

infra-down:
	docker compose down

frontend-dev:
	npm --prefix frontend run dev

backend-dev:
	.venv/bin/uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

worker-dev:
	PYTHONPATH=backend:retrieval/src .venv/bin/python -m app.worker

ingestion-help:
	.venv/bin/python -m beken_ingestion --help

retrieval-help:
	.venv/bin/python -m beken_retrieval --help

db-test:
	docker compose up -d --wait postgres
	BEKEN_RUN_DB_TESTS=1 .venv/bin/pytest backend/tests/test_stage3_database_integration.py backend/tests/test_stage4_database_integration.py ingestion/tests/test_database_integration.py retrieval/tests/test_postgres_integration.py

test:
	.venv/bin/pytest backend/tests ingestion/tests retrieval/tests

lint:
	npm --prefix frontend run lint
	.venv/bin/ruff check backend ingestion retrieval

build:
	npm --prefix frontend run build

validate: lint test build
	docker compose config --quiet
