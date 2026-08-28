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


async def count_corpus_documents(settings: Settings) -> int:
    connection = await psycopg.AsyncConnection.connect(
        settings.database_url,
        connect_timeout=max(1, int(settings.dependency_timeout_seconds)),
    )
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute("select to_regclass('legal.documents')")
            relation = await cursor.fetchone()
            if not relation or relation[0] is None:
                return 0
            await cursor.execute("select count(*) from legal.documents")
            row = await cursor.fetchone()
            return int(row[0]) if row else 0


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
    corpus_documents = await count_corpus_documents(settings) if postgres.status == "ready" else 0
    return {
        "status": "ready" if is_ready else "not_ready",
        "corpus_documents": corpus_documents,
        "dependencies": dependencies,
    }
