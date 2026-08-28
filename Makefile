.PHONY: setup infra-up infra-down frontend-dev backend-dev ingestion-help test lint build validate

setup:
	npm --prefix frontend ci
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e "./backend[dev]"
	.venv/bin/pip install -e "./ingestion[dev]"

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

test:
	.venv/bin/pytest backend/tests ingestion/tests

lint:
	npm --prefix frontend run lint
	.venv/bin/ruff check backend ingestion

build:
	npm --prefix frontend run build

validate: lint test build
	docker compose config --quiet
