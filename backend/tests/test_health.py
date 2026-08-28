import httpx
import pytest

from app.core import health
from app.core.health import DependencyHealth
from app.main import app


def api_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


@pytest.mark.asyncio
async def test_liveness() -> None:
    async with api_client() as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Beken.ai API",
        "version": "0.1.0",
    }


@pytest.mark.asyncio
async def test_readiness_when_dependencies_are_ready(monkeypatch) -> None:
    async def ready_dependency(_settings):
        return DependencyHealth(status="ready")

    async def corpus_count(_settings):
        return 0

    monkeypatch.setattr(health, "check_postgres", ready_dependency)
    monkeypatch.setattr(health, "check_qdrant", ready_dependency)
    monkeypatch.setattr(health, "count_corpus_documents", corpus_count)

    async with api_client() as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["corpus_documents"] == 0
    assert payload["dependencies"]["postgres"]["status"] == "ready"
    assert payload["dependencies"]["qdrant"]["status"] == "ready"


@pytest.mark.asyncio
async def test_readiness_returns_503_when_dependency_is_unavailable(monkeypatch) -> None:
    async def unavailable_postgres(_settings):
        return DependencyHealth(status="unavailable", detail="connection refused")

    async def ready_qdrant(_settings):
        return DependencyHealth(status="ready")

    monkeypatch.setattr(health, "check_postgres", unavailable_postgres)
    monkeypatch.setattr(health, "check_qdrant", ready_qdrant)

    async with api_client() as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["corpus_documents"] == 0
