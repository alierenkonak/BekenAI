.PHONY: setup infra-up infra-down frontend-dev backend-dev test lint build validate

setup:
	npm --prefix frontend install
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e "./backend[dev]"

infra-up:
	docker compose up -d --wait

infra-down:
	docker compose down

frontend-dev:
	npm --prefix frontend run dev

backend-dev:
	.venv/bin/uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000

test:
	.venv/bin/pytest backend/tests

lint:
	npm --prefix frontend run lint
	.venv/bin/ruff check backend

build:
	npm --prefix frontend run build

validate: lint test build
	docker compose config --quiet

