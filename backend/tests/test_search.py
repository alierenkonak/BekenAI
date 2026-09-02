from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from beken_retrieval.coordinator import (
    DomainSearchCoordinator,
    HybridDomainIndex,
    InMemoryIndexRegistry,
)
from beken_retrieval.models import ChunkRecord, SearchFilters, SearchHit
from beken_retrieval.reranking import IdentityReranker

from app.api import search as search_api
from app.api.search import get_search_coordinator
from app.main import app


class StaticRetriever:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits

    def search(self, query: str, *, filters: SearchFilters, limit: int) -> list[SearchHit]:
        return self.hits[:limit]


def api_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def fixture_hit(*, source_url: str = "https://www.mevzuat.gov.tr/") -> SearchHit:
    record = ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id="law-4857-current",
        domain_code="labour_law",
        corpus_version="labour-law-pilot-v4",
        retrieval_scope_version="labour-law-v1",
        domain_role="core",
        document_type="law",
        title="4857 sayılı İş Kanunu",
        text="Fesih bildirimi yazılı olarak yapılmalıdır.",
        section_type="article",
        breadcrumb=("4857", "Madde 19"),
        page_number=12,
        legislation_numbers=("4857",),
        article_labels=("19",),
        source_url=source_url,
    )
    return SearchHit(record=record, score=1.0, rank=1, score_breakdown={"bm25": 1.0})


@pytest.mark.asyncio
async def test_search_returns_503_when_domain_index_is_not_ready() -> None:
    app.dependency_overrides[get_search_coordinator] = lambda: DomainSearchCoordinator(
        InMemoryIndexRegistry()
    )
    try:
        async with api_client() as client:
            response = await client.post(
                "/search", json={"query": "fesih bildirimi", "mode": "bm25"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "retrieval_index_not_ready"


@pytest.mark.asyncio
async def test_search_returns_empty_200_for_no_matches() -> None:
    empty = StaticRetriever([])
    index = HybridDomainIndex(
        "labour_law",
        "labour-law-pilot-v4",
        "test-index",
        lexical=empty,
    )
    app.dependency_overrides[get_search_coordinator] = lambda: DomainSearchCoordinator(
        InMemoryIndexRegistry((index,))
    )
    try:
        async with api_client() as client:
            response = await client.post(
                "/search", json={"query": "eşleşmeyen soru", "mode": "bm25"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.asyncio
async def test_search_returns_traceable_exact_passage() -> None:
    hit = fixture_hit()
    retriever = StaticRetriever([hit])
    index = HybridDomainIndex(
        "labour_law",
        "labour-law-pilot-v4",
        "test-index",
        lexical=retriever,
        dense=retriever,
        reranker=IdentityReranker(),
    )
    app.dependency_overrides[get_search_coordinator] = lambda: DomainSearchCoordinator(
        InMemoryIndexRegistry((index,))
    )
    try:
        async with api_client() as client:
            response = await client.post(
                "/search",
                json={"query": "fesih bildirimi", "mode": "hybrid_rerank"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["chunk_id"] == hit.record.chunk_id
    assert result["exact_passage"] == hit.record.text
    assert result["index_version"] == "test-index"


@pytest.mark.asyncio
async def test_doctrine_is_opt_in_and_returned_in_a_separate_channel() -> None:
    primary_hit = fixture_hit()
    doctrine_hit = SearchHit(
        record=replace(
            primary_hit.record,
            chunk_id=str(uuid4()),
            parse_id=str(uuid4()),
            document_id=str(uuid4()),
            source_document_id="course-note-2026",
            corpus_version="labour-law-doctrine-v1",
            retrieval_scope_version="labour-law-doctrine-v1",
            domain_role="supplemental",
            source_kind="doctrine",
            document_type="course_note",
            title="İş Hukuku Ders Notu (2026)",
            author="Örnek Yazar",
            publication_year=2026,
            citation_text="Örnek Yazar, İş Hukuku Ders Notu, 2026.",
        ),
        score=0.9,
        rank=1,
        score_breakdown={"bm25": 0.9},
    )
    registry = InMemoryIndexRegistry(
        (
            HybridDomainIndex(
                "labour_law",
                "labour-law-pilot-v4",
                "primary-index",
                lexical=StaticRetriever([primary_hit]),
            ),
            HybridDomainIndex(
                "labour_law",
                "labour-law-doctrine-v1",
                "doctrine-index",
                channel="doctrine",
                lexical=StaticRetriever([doctrine_hit]),
            ),
        )
    )
    app.dependency_overrides[get_search_coordinator] = lambda: DomainSearchCoordinator(
        registry
    )
    try:
        async with api_client() as client:
            without_doctrine = await client.post(
                "/search", json={"query": "fesih bildirimi", "mode": "bm25"}
            )
            with_doctrine = await client.post(
                "/search",
                json={
                    "query": "fesih bildirimi",
                    "mode": "bm25",
                    "include_doctrine": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert without_doctrine.status_code == 200
    assert without_doctrine.json()["doctrine_results"] == []
    assert with_doctrine.status_code == 200
    payload = with_doctrine.json()
    assert payload["results"][0]["source_channel"] == "primary"
    assert payload["doctrine_results"][0]["source_channel"] == "doctrine"
    assert payload["doctrine_results"][0]["source_kind"] == "doctrine"
    assert payload["doctrine_results"][0]["author"] == "Örnek Yazar"
    assert payload["doctrine_results"][0]["index_version"] == "doctrine-index"


@pytest.mark.asyncio
async def test_search_validates_query_limit_and_date_range() -> None:
    async with api_client() as client:
        response = await client.post(
            "/search",
            json={
                "query": "x",
                "limit": 21,
                "filters": {"date_from": "2025-01-02", "date_to": "2025-01-01"},
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_rejects_invalid_domain_codes() -> None:
    async with api_client() as client:
        response = await client.post(
            "/search",
            json={"query": "geçerli soru", "domains": ["../../private"]},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_does_not_expose_non_http_source_urls() -> None:
    hit = fixture_hit(source_url="javascript:alert(1)")
    retriever = StaticRetriever([hit])
    index = HybridDomainIndex(
        "labour_law",
        "labour-law-pilot-v4",
        "test-index",
        lexical=retriever,
    )
    app.dependency_overrides[get_search_coordinator] = lambda: DomainSearchCoordinator(
        InMemoryIndexRegistry((index,))
    )
    try:
        async with api_client() as client:
            response = await client.post(
                "/search", json={"query": "fesih bildirimi", "mode": "bm25"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["results"][0]["source_url"] is None


def test_frontend_source_does_not_reference_backend_secrets() -> None:
    source = Path("frontend/app/page.tsx").read_text(encoding="utf-8")
    assert "SUPABASE_SECRET" not in source
    assert "QDRANT_API_KEY" not in source
    assert "SUPABASE_DB_URL" not in source


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"query": "x"},
    {"query": "geçerli soru", "domains": ["../../private"]},
    {"query": "geçerli soru", "limit": 21},
])
async def test_invalid_request_never_initializes_models(monkeypatch, body) -> None:
    calls = []

    def forbidden_loader(*args):
        calls.append(True)
        raise AssertionError("Model initialization must not run")

    app.dependency_overrides.pop(get_search_coordinator)
    monkeypatch.setattr(search_api, "FilesystemIndexRegistry", forbidden_loader)
    async with api_client() as client:
        response = await client.post("/search", json=body)
    assert response.status_code == 422
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["initialize", "search", "hydrate"])
@pytest.mark.parametrize("message", [
    "Authorization: Bearer TEST_ONLY_SECRET_SENTINEL",
    "https://user:TEST_ONLY_SECRET_SENTINEL@example.invalid/?token=TEST_ONLY_SECRET_SENTINEL",
])
async def test_search_failures_do_not_disclose_provider_details(
    monkeypatch, caplog, capsys, failure_stage, message
) -> None:
    def fail(*args, **kwargs):
        raise ConnectionError(message)

    if failure_stage == "initialize":
        app.dependency_overrides.pop(get_search_coordinator)
        monkeypatch.setattr(search_api, "FilesystemIndexRegistry", fail)
    else:
        coordinator = DomainSearchCoordinator(InMemoryIndexRegistry())
        if failure_stage == "search":
            monkeypatch.setattr(coordinator, "search", fail)
        else:
            monkeypatch.setattr(coordinator, "search", lambda *args, **kwargs: [fixture_hit()])
            monkeypatch.setattr(coordinator.registry, "get", fail)
        app.dependency_overrides[get_search_coordinator] = lambda: coordinator

    async with api_client() as client:
        response = await client.post("/search", json={"query": "fesih bildirimi"})
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "retrieval_index_not_ready",
        "message": "Search service is temporarily unavailable",
    }
    captured = capsys.readouterr()
    visible_output = response.text + caplog.text + captured.out + captured.err
    assert "TEST_ONLY_SECRET_SENTINEL" not in visible_output
    assert "ConnectionError" in caplog.text


def test_backend_unit_tests_block_real_network() -> None:
    import socket

    with pytest.raises(RuntimeError, match="Network access is disabled"):
        socket.create_connection(("example.invalid", 443))


@pytest.mark.asyncio
async def test_valid_requests_use_cached_loader_and_preserve_results(monkeypatch) -> None:
    hit = fixture_hit()
    index = HybridDomainIndex(
        "labour_law", "labour-law-pilot-v4", "test-index", lexical=StaticRetriever([hit])
    )
    calls = []

    def load_registry(settings):
        calls.append(True)
        return InMemoryIndexRegistry((index,))

    app.dependency_overrides.pop(get_search_coordinator)
    monkeypatch.setattr(search_api, "FilesystemIndexRegistry", load_registry)
    async with api_client() as client:
        for _ in range(2):
            response = await client.post(
                "/search", json={"query": "fesih bildirimi", "mode": "bm25"}
            )
            assert response.status_code == 200
            assert response.json()["results"][0]["exact_passage"] == hit.record.text
    assert len(calls) == 1
