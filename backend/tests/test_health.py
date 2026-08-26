from fastapi.testclient import TestClient

from app.core import health
from app.core.health import DependencyHealth
from app.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Beken.ai API",
        "version": "0.1.0",
    }


def test_readiness_when_dependencies_are_ready(monkeypatch) -> None:
    async def ready_dependency(_settings):
        return DependencyHealth(status="ready")

    monkeypatch.setattr(health, "check_postgres", ready_dependency)
    monkeypatch.setattr(health, "check_qdrant", ready_dependency)

    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["corpus_documents"] == 0
    assert payload["dependencies"]["postgres"]["status"] == "ready"
    assert payload["dependencies"]["qdrant"]["status"] == "ready"


def test_readiness_returns_503_when_dependency_is_unavailable(monkeypatch) -> None:
    async def unavailable_postgres(_settings):
        return DependencyHealth(status="unavailable", detail="connection refused")

    async def ready_qdrant(_settings):
        return DependencyHealth(status="ready")

    monkeypatch.setattr(health, "check_postgres", unavailable_postgres)
    monkeypatch.setattr(health, "check_qdrant", ready_qdrant)

    response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["corpus_documents"] == 0
