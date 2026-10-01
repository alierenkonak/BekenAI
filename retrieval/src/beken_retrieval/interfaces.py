from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from beken_retrieval.models import SearchFilters, SearchHit


class LexicalRetriever(Protocol):
    def search(self, query: str, *, filters: SearchFilters, limit: int) -> list[SearchHit]: ...


class DenseRetriever(Protocol):
    def search(self, query: str, *, filters: SearchFilters, limit: int) -> list[SearchHit]: ...


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[SearchHit], *, limit: int) -> list[SearchHit]: ...


class IndexRegistry(Protocol):
    def get(self, domain_code: str, channel: str = "primary") -> DomainIndex | None: ...

    def supported_domains(self, channel: str = "primary") -> tuple[str, ...]: ...


class DomainIndex(Protocol):
    domain_code: str
    channel: str
    corpus_version: str
    index_version: str

    def search(
        self,
        query: str,
        *,
        mode: str,
        filters: SearchFilters,
        limit: int,
    ) -> list[SearchHit]: ...

    def article_hits(
        self,
        references: Sequence[tuple[str, str]],
        *,
        filters: SearchFilters,
        per_article: int = 2,
    ) -> list[SearchHit]: ...
