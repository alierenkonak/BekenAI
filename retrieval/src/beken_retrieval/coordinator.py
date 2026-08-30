from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum

from beken_retrieval.fusion import reciprocal_rank_fusion
from beken_retrieval.interfaces import DenseRetriever, IndexRegistry, LexicalRetriever, Reranker
from beken_retrieval.models import SearchFilters, SearchHit


class SearchMode(StrEnum):
    BM25 = "bm25"
    VECTOR = "vector"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


class IndexNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True)
class HybridDomainIndex:
    domain_code: str
    corpus_version: str
    index_version: str
    lexical: LexicalRetriever | None = None
    dense: DenseRetriever | None = None
    reranker: Reranker | None = None
    hybrid_candidate_limit: int = 50

    def search(
        self,
        query: str,
        *,
        mode: str,
        filters: SearchFilters,
        limit: int,
    ) -> list[SearchHit]:
        selected = SearchMode(mode)
        candidate_limit = max(limit, self.hybrid_candidate_limit)
        if selected is SearchMode.BM25:
            if not self.lexical:
                raise IndexNotReadyError(f"BM25 index is not ready for {self.domain_code}")
            return self.lexical.search(query, filters=filters, limit=limit)
        if selected is SearchMode.VECTOR:
            if not self.dense:
                raise IndexNotReadyError(f"Vector index is not ready for {self.domain_code}")
            return self.dense.search(query, filters=filters, limit=limit)
        if not self.lexical or not self.dense:
            raise IndexNotReadyError(f"Hybrid index is not ready for {self.domain_code}")
        lexical = self.lexical.search(query, filters=filters, limit=candidate_limit)
        dense = self.dense.search(query, filters=filters, limit=candidate_limit)
        fused = reciprocal_rank_fusion(
            (lexical, dense), limit=candidate_limit, score_key="hybrid_rrf"
        )
        if selected is SearchMode.HYBRID:
            return [hit.with_rank(rank) for rank, hit in enumerate(fused[:limit], start=1)]
        if not self.reranker:
            raise IndexNotReadyError(f"Reranker is not ready for {self.domain_code}")
        return self.reranker.rerank(query, fused, limit=limit)


class InMemoryIndexRegistry:
    def __init__(self, indexes: tuple[HybridDomainIndex, ...] = ()) -> None:
        self.indexes = {index.domain_code: index for index in indexes}

    def get(self, domain_code: str) -> HybridDomainIndex | None:
        return self.indexes.get(domain_code)

    def supported_domains(self) -> tuple[str, ...]:
        return tuple(sorted(self.indexes))


class DomainSearchCoordinator:
    def __init__(self, registry: IndexRegistry) -> None:
        self.registry = registry

    def search(
        self,
        query: str,
        *,
        domains: tuple[str, ...],
        mode: str,
        filters: SearchFilters,
        limit: int,
    ) -> list[SearchHit]:
        requested = self.registry.supported_domains() if domains == ("all",) else domains
        if not requested:
            raise IndexNotReadyError("No supported retrieval domain is configured")
        indexes = []
        for domain in requested:
            index = self.registry.get(domain)
            if index is None:
                raise IndexNotReadyError(f"Index is not ready for domain {domain!r}")
            indexes.append(index)
        if len(indexes) == 1:
            return indexes[0].search(query, mode=mode, filters=filters, limit=limit)
        with ThreadPoolExecutor(max_workers=min(8, len(indexes))) as executor:
            futures = [
                executor.submit(
                    index.search,
                    query,
                    mode=mode,
                    filters=filters,
                    limit=max(50, limit),
                )
                for index in indexes
            ]
            rankings = [future.result() for future in futures]
        return reciprocal_rank_fusion(rankings, limit=limit, score_key="cross_domain_rrf")
