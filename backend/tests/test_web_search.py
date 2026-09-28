from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.core.repository import get_repository
from app.main import app
from app.web.search import (
    EXCLUDED_DOMAINS,
    MAX_QUERY_CHARS,
    TAVILY_SEARCH_URL,
    TavilyWebSearch,
    TransientWebSearchError,
    WebSearchError,
)


def web_settings(**overrides) -> Settings:
    return Settings(_env_file=None, tavily_api_key="tvly-test", **overrides)


def client_for(handler) -> TavilyWebSearch:
    return TavilyWebSearch(web_settings(), transport=httpx.MockTransport(handler))


def test_web_search_needs_a_non_blank_key() -> None:
    assert web_settings().web_search_enabled
    assert not Settings(_env_file=None).web_search_enabled
    assert not Settings(_env_file=None, tavily_api_key="   ").web_search_enabled
    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        _ = Settings(_env_file=None).tavily_secret


@pytest.mark.asyncio
async def test_search_asks_tavily_for_turkish_page_excerpts_and_keeps_usable_hits() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=4857",
                        "title": "  İş   Kanunu ",
                        "content": "Madde 14 [...] Uzaktan çalışma",
                        "score": 0.91,
                        "published_date": "2024-03-01T10:00:00Z",
                    },
                    {
                        "url": "https://hukuk.example.com/yazi",
                        "title": "",
                        "content": "Yemek ücreti işyeri uygulamasına bağlıdır.",
                        "score": "bad",
                        "published_date": "Wed, 15 Jan 2025 10:00:00 GMT",
                    },
                    # Duplicates, non-web links and empty excerpts are dropped.
                    {"url": "https://hukuk.example.com/yazi", "content": "tekrar"},
                    {"url": "ftp://files.example.com/a", "content": "dosya"},
                    {"url": "https://bos.example.com", "content": "   "},
                ]
            },
        )

    hits = await client_for(handler).search("uzaktan çalışma yemek ücreti " * 40)

    [request] = seen
    body = json.loads(request.content)
    assert str(request.url) == TAVILY_SEARCH_URL
    assert request.headers["Authorization"] == "Bearer tvly-test"
    assert len(body["query"]) <= MAX_QUERY_CHARS
    assert body["search_depth"] == "advanced" and body["country"] == "turkey"
    assert body["include_raw_content"] is False and body["include_answer"] is False
    assert body["exclude_domains"] == list(EXCLUDED_DOMAINS)

    assert [hit.site for hit in hits] == ["mevzuat.gov.tr", "hukuk.example.com"]
    assert hits[0].title == "İş Kanunu" and hits[1].title == "hukuk.example.com"
    assert hits[0].published_date == "2024-03-01" and hits[1].published_date == "2025-01-15"
    assert hits[1].score == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error", "code"),
    [
        (432, WebSearchError, "web_search_quota_exceeded"),
        (433, WebSearchError, "web_search_quota_exceeded"),
        (401, WebSearchError, "web_search_unavailable"),
        (400, WebSearchError, "web_search_failed"),
        (429, TransientWebSearchError, "web_search_temporarily_unavailable"),
        (502, TransientWebSearchError, "web_search_temporarily_unavailable"),
    ],
)
async def test_tavily_errors_map_to_safe_codes(status, error, code) -> None:
    search = client_for(lambda _request: httpx.Response(status, json={"detail": "secret"}))
    with pytest.raises(error, match=code) as raised:
        await search.search("fesih")
    # A spent quota or a bad key will not fix itself; only outages are retried.
    assert isinstance(raised.value, TransientWebSearchError) == (error is TransientWebSearchError)


@pytest.mark.asyncio
async def test_an_unreachable_tavily_is_a_transient_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(TransientWebSearchError, match="web_search_temporarily_unavailable"):
        await client_for(handler).search("fesih")


class RefusingRepository:
    async def enqueue_chat(self, *_args, **_kwargs):
        raise AssertionError("a web chat must not be queued while web search is off")


async def _call(settings: Settings, method: str, path: str, **kwargs) -> httpx.Response:
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repository] = RefusingRepository
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_capabilities_report_web_search_without_revealing_the_key() -> None:
    enabled = await _call(web_settings(), "GET", "/chat/capabilities")
    disabled = await _call(Settings(_env_file=None), "GET", "/chat/capabilities")

    assert enabled.json() == {"web_search": True}
    assert disabled.json() == {"web_search": False}
    assert "tvly" not in enabled.text


@pytest.mark.asyncio
async def test_a_web_chat_is_refused_while_web_search_is_not_configured() -> None:
    response = await _call(
        Settings(_env_file=None),
        "POST",
        "/chat",
        json={"message": "Uzaktan çalışana yemek ücreti ödenir mi?", "search_mode": "web"},
        headers={"Idempotency-Key": "web-search-off-1"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "web_search_unavailable"
