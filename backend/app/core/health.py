from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

import httpx
import psycopg

from app.core.config import Settings


@dataclass(frozen=True)
class DependencyHealth:
    status: str
    detail: str | None = None


async def check_postgres(settings: Settings) -> DependencyHealth:
    try:
        connection = await psycopg.AsyncConnection.connect(
            settings.database_url,
            connect_timeout=max(1, int(settings.dependency_timeout_seconds)),
        )
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                await cursor.fetchone()
        return DependencyHealth(status="ready")
    except Exception as exc:  # health endpoint must normalize driver failures
        return DependencyHealth(status="unavailable", detail=type(exc).__name__)


async def check_qdrant(settings: Settings) -> DependencyHealth:
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else None
    try:
        timeout = httpx.Timeout(settings.dependency_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.get(f"{settings.qdrant_url.rstrip('/')}/healthz")
            response.raise_for_status()
        return DependencyHealth(status="ready")
    except Exception as exc:  # health endpoint must normalize client failures
        return DependencyHealth(status="unavailable", detail=type(exc).__name__)


async def readiness(settings: Settings) -> dict:
    postgres, qdrant = await asyncio.gather(
        check_postgres(settings),
        check_qdrant(settings),
    )
    dependencies = {
        "postgres": asdict(postgres),
        "qdrant": asdict(qdrant),
    }
    is_ready = all(item["status"] == "ready" for item in dependencies.values())
    return {
        "status": "ready" if is_ready else "not_ready",
        "corpus_documents": 0,
        "dependencies": dependencies,
    }
