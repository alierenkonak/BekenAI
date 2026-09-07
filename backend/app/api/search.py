from __future__ import annotations

import logging
import re
from datetime import date
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from beken_retrieval.config import get_settings as get_retrieval_settings
from beken_retrieval.coordinator import (
    DomainSearchCoordinator,
    SearchMode,
)
from beken_retrieval.models import SearchFilters, SearchHit
from beken_retrieval.registry import FilesystemIndexRegistry
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.auth import CurrentUser

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)


class SearchFilterRequest(BaseModel):
    document_types: list[str] = Field(default_factory=list)
    authorities: list[str] = Field(default_factory=list)
    chambers: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    legislation_numbers: list[str] = Field(default_factory=list)
    article_labels: list[str] = Field(default_factory=list)
    section_types: list[str] = Field(default_factory=list)
    domain_roles: list[Literal["core", "supplemental", "future_domain"]] = Field(
        default_factory=lambda: ["core", "supplemental"]
    )

    @model_validator(mode="after")
    def validate_date_range(self) -> SearchFilterRequest:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to")
        for name in (
            "document_types",
            "authorities",
            "chambers",
            "legislation_numbers",
            "article_labels",
            "section_types",
            "domain_roles",
        ):
            values = getattr(self, name)
            if len(values) > 50 or any(not value.strip() or len(value) > 100 for value in values):
                raise ValueError(f"{name} contains too many or invalid filter values")
        return self

    def to_domain_filters(self) -> SearchFilters:
        return SearchFilters(
            document_types=tuple(self.document_types),
            authorities=tuple(self.authorities),
            chambers=tuple(self.chambers),
            date_from=self.date_from,
            date_to=self.date_to,
            legislation_numbers=tuple(self.legislation_numbers),
            article_labels=tuple(self.article_labels),
            section_types=tuple(self.section_types),
            domain_roles=tuple(self.domain_roles),
        )


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    domains: list[str] = Field(default_factory=lambda: ["labour_law"], min_length=1, max_length=8)
    mode: SearchMode = SearchMode.HYBRID_RERANK
    limit: int = Field(default=10, ge=1, le=20)
    include_doctrine: bool = False
    filters: SearchFilterRequest = Field(default_factory=SearchFilterRequest)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("query must contain at least 3 non-whitespace characters")
        return stripped

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized:
            raise ValueError("at least one domain is required")
        if "all" in normalized and normalized != ["all"]:
            raise ValueError("all cannot be combined with explicit domains")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{1,49}", value) for value in normalized):
            raise ValueError("domain codes must use lowercase snake_case")
        return list(dict.fromkeys(normalized))


class SearchResult(BaseModel):
    source_channel: Literal["primary", "doctrine"]
    source_kind: str
    domain: str
    rank: int
    score: float
    score_breakdown: dict[str, float]
    document_id: str
    parse_id: str
    chunk_id: str
    title: str
    document_type: str
    authority: str | None
    chamber: str | None
    case_number: str | None
    decision_number: str | None
    document_date: date | None
    breadcrumb: list[str]
    section_type: str
    page_number: int | None
    exact_passage: str
    source_url: str | None
    corpus_version: str
    retrieval_scope_version: str
    index_version: str
    author: str | None
    publication_year: int | None
    citation_text: str | None


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    domains: list[str]
    results: list[SearchResult]
    doctrine_results: list[SearchResult] = Field(default_factory=list)


@lru_cache
def _load_search_coordinator() -> DomainSearchCoordinator:
    return DomainSearchCoordinator(FilesystemIndexRegistry(get_retrieval_settings()))


def _unavailable(exc: Exception) -> HTTPException:
    # Never log/return provider exception text, headers, URLs, or chained tracebacks.
    logger.warning("Search unavailable (%s)", type(exc).__name__)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "retrieval_index_not_ready",
            "message": "Search service is temporarily unavailable",
        },
    )


def get_search_coordinator(payload: SearchRequest) -> DomainSearchCoordinator:
    # FastAPI validates the request before the expensive cached loader runs.
    try:
        return _load_search_coordinator()
    except Exception as exc:
        raise _unavailable(exc) from None


SearchCoordinator = Annotated[DomainSearchCoordinator, Depends(get_search_coordinator)]


def _safe_source_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    return value if parts.scheme in {"http", "https"} and parts.netloc else None


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest, coordinator: SearchCoordinator, user: CurrentUser
) -> SearchResponse:
    try:
        hits = await run_in_threadpool(
            coordinator.search,
            payload.query,
            domains=tuple(payload.domains),
            mode=payload.mode.value,
            filters=payload.filters.to_domain_filters(),
            limit=payload.limit,
        )
        doctrine_hits: list[SearchHit] = []
        if payload.include_doctrine:
            doctrine_hits = await run_in_threadpool(
                coordinator.search,
                payload.query,
                domains=tuple(payload.domains),
                mode=payload.mode.value,
                filters=payload.filters.to_domain_filters(),
                limit=payload.limit,
                channel="doctrine",
            )
        return _build_response(payload, coordinator, hits, doctrine_hits)
    except Exception as exc:
        raise _unavailable(exc) from None


def _build_response(
    payload: SearchRequest,
    coordinator: DomainSearchCoordinator,
    hits: list[SearchHit],
    doctrine_hits: list[SearchHit] | None = None,
) -> SearchResponse:
    results = _build_results(coordinator, hits, channel="primary")
    doctrine_results = _build_results(coordinator, doctrine_hits or [], channel="doctrine")
    return SearchResponse(
        query=payload.query,
        mode=payload.mode,
        domains=payload.domains,
        results=results,
        doctrine_results=doctrine_results,
    )


def _build_results(
    coordinator: DomainSearchCoordinator,
    hits: list[SearchHit],
    *,
    channel: Literal["primary", "doctrine"],
) -> list[SearchResult]:
    results = []
    for hit in hits:
        index = coordinator.registry.get(hit.record.domain_code, channel)
        if index is None:
            continue
        results.append(
            SearchResult(
                source_channel=channel,
                source_kind=hit.record.source_kind,
                domain=hit.record.domain_code,
                rank=hit.rank,
                score=hit.score,
                score_breakdown=hit.score_breakdown,
                document_id=hit.record.document_id,
                parse_id=hit.record.parse_id,
                chunk_id=hit.record.chunk_id,
                title=hit.record.title,
                document_type=hit.record.document_type,
                authority=hit.record.authority,
                chamber=hit.record.chamber,
                case_number=hit.record.case_number,
                decision_number=hit.record.decision_number,
                document_date=hit.record.document_date,
                breadcrumb=list(hit.record.breadcrumb),
                section_type=hit.record.section_type,
                page_number=hit.record.page_number,
                exact_passage=hit.record.text,
                source_url=_safe_source_url(hit.record.source_url),
                corpus_version=hit.record.corpus_version,
                retrieval_scope_version=hit.record.retrieval_scope_version,
                index_version=index.index_version,
                author=hit.record.author,
                publication_year=hit.record.publication_year,
                citation_text=hit.record.citation_text,
            )
        )
    return results
