from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings

logger = logging.getLogger("bekenai.web")

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
# Tavily works best with queries under 400 characters.
MAX_QUERY_CHARS = 400
# Social media, video and Q&A pages rarely state the law; they only crowd out pages that do.
EXCLUDED_DOMAINS = (
    "eksisozluk.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "quora.com",
    "reddit.com",
    "sikayetvar.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
)
SAFE_WEB_SEARCH_ERRORS = frozenset(
    {
        "web_search_unavailable",
        "web_search_quota_exceeded",
        "web_search_temporarily_unavailable",
        "web_search_failed",
    }
)


class WebSearchError(RuntimeError):
    """A web search that cannot succeed as asked; the message is always a safe code."""


class TransientWebSearchError(WebSearchError):
    """Rate limits, outages and timeouts: the job may be retried."""


@dataclass(frozen=True)
class WebHit:
    url: str
    title: str
    site: str
    # Up to three short excerpts of the page that matched the query.
    text: str
    score: float
    retrieved_on: str
    published_date: str | None = None


class TavilyWebSearch:
    """Searches the web through Tavily, which returns page excerpts the verifier can check."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.api_key = settings.tavily_secret
        self.depth = settings.web_search_depth
        self.max_results = settings.web_search_max_results
        self.timeout = settings.web_search_timeout_seconds
        self.transport = transport

    @property
    def index_version(self) -> str:
        return f"tavily-{self.depth}"

    async def search(self, query: str) -> list[WebHit]:
        payload = {
            "query": " ".join(query.split())[:MAX_QUERY_CHARS],
            "search_depth": self.depth,
            "max_results": self.max_results,
            "chunks_per_source": 3,
            "country": "turkey",
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_published_date": True,
            "exclude_domains": list(EXCLUDED_DOMAINS),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(
                    TAVILY_SEARCH_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("Web search unreachable (%s)", type(exc).__name__)
            raise TransientWebSearchError("web_search_temporarily_unavailable") from None
        status = response.status_code
        if status != 200:
            # The status alone is safe to log; the body may echo the query.
            logger.warning("Web search failed (status=%s)", status)
        if status in (432, 433):
            raise WebSearchError("web_search_quota_exceeded")
        if status == 429 or status >= 500:
            raise TransientWebSearchError("web_search_temporarily_unavailable")
        if status in (401, 403):
            raise WebSearchError("web_search_unavailable")
        if status != 200:
            raise WebSearchError("web_search_failed")
        try:
            results = response.json().get("results") or []
        except (ValueError, AttributeError):
            raise TransientWebSearchError("web_search_temporarily_unavailable") from None
        return _hits(results)


def _hits(results: list) -> list[WebHit]:
    retrieved_on = datetime.now(UTC).date().isoformat()
    hits: list[WebHit] = []
    seen: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        text = str(item.get("content") or "").strip()
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc or not text or url in seen:
            continue
        seen.add(url)
        site = parts.netloc.lower().removeprefix("www.")
        title = " ".join(str(item.get("title") or "").split()) or site
        try:
            score = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        hits.append(
            WebHit(
                url=url,
                title=title[:300],
                site=site,
                text=text,
                score=score,
                retrieved_on=retrieved_on,
                published_date=_published(item.get("published_date")),
            )
        )
    return hits


def _published(value: object) -> str | None:
    """Tavily dates come as ISO or RFC 2822 text; keep only a valid calendar date."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return None
