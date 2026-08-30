from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

import pytest

from beken_retrieval.cli import _draft_relevance, _pool_hits
from beken_retrieval.coordinator import (
    DomainSearchCoordinator,
    HybridDomainIndex,
    IndexNotReadyError,
    InMemoryIndexRegistry,
)
from beken_retrieval.evaluation import (
    load_queries,
    quality_gate,
    reviewed_queries,
    select_embedding_model,
)
from beken_retrieval.fusion import reciprocal_rank_fusion
from beken_retrieval.models import ChunkRecord, SearchFilters, SearchHit
from beken_retrieval.reranking import IdentityReranker


def record(domain: str, label: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id=label,
        domain_code=domain,
        corpus_version="v1",
        retrieval_scope_version="scope-v1",
        domain_role="core",
        document_type="law",
        title=label,
        text=label,
        section_type="article",
    )


@dataclass
class StaticRetriever:
    hits: list[SearchHit]

    def search(self, query: str, *, filters: SearchFilters, limit: int) -> list[SearchHit]:
        return self.hits[:limit]


def test_rrf_is_deterministic_for_ties() -> None:
    first = record("labour_law", "a")
    second = record("labour_law", "b")
    ranking_a = [SearchHit(first, 1.0), SearchHit(second, 0.5)]
    ranking_b = [SearchHit(second, 1.0), SearchHit(first, 0.5)]

    one = reciprocal_rank_fusion((ranking_a, ranking_b), limit=2)
    two = reciprocal_rank_fusion((ranking_a, ranking_b), limit=2)

    assert [hit.record.chunk_id for hit in one] == [hit.record.chunk_id for hit in two]
    assert [hit.record.chunk_id for hit in one] == sorted([first.chunk_id, second.chunk_id])


def test_multi_domain_coordinator_fuses_separate_indexes() -> None:
    labour = record("labour_law", "labour")
    tax = record("tax_law", "tax")
    registry = InMemoryIndexRegistry(
        (
            HybridDomainIndex(
                "labour_law", "v1", "i1", lexical=StaticRetriever([SearchHit(labour, 1)])
            ),
            HybridDomainIndex("tax_law", "v1", "i2", lexical=StaticRetriever([SearchHit(tax, 1)])),
        )
    )

    results = DomainSearchCoordinator(registry).search(
        "ortak sorgu",
        domains=("labour_law", "tax_law"),
        mode="bm25",
        filters=SearchFilters(),
        limit=10,
    )

    assert {hit.record.domain_code for hit in results} == {"labour_law", "tax_law"}


def test_hybrid_requires_both_indexes_and_reranker() -> None:
    registry = InMemoryIndexRegistry(
        (HybridDomainIndex("labour_law", "v1", "i1", lexical=StaticRetriever([])),)
    )

    with pytest.raises(IndexNotReadyError):
        DomainSearchCoordinator(registry).search(
            "sorgu",
            domains=("labour_law",),
            mode="hybrid_rerank",
            filters=SearchFilters(),
            limit=10,
        )


def test_identity_reranker_keeps_candidate_order() -> None:
    item = record("labour_law", "a")
    hits = [SearchHit(item, 1.0)]
    assert IdentityReranker().rerank("q", hits, limit=1)[0].rank == 1


def test_evaluation_draft_has_expected_split_and_cannot_pass_unreviewed() -> None:
    queries = load_queries(__import__("pathlib").Path("evals/labour_law/queries.v1.jsonl"))

    assert len(queries) == 120
    assert sum(query.split == "development" for query in queries) == 70
    assert sum(query.split == "holdout" for query in queries) == 30
    assert sum(query.split == "coverage_candidate" for query in queries) == 20
    assert reviewed_queries(queries) == []


def test_embedding_tie_selects_lower_latency_model() -> None:
    reports = {
        "e5_vector": {
            "ndcg_at_10": 0.70,
            "p95_latency_seconds": 0.5,
            "peak_process_memory_gb": 2.0,
        },
        "bge_m3_vector": {
            "ndcg_at_10": 0.705,
            "p95_latency_seconds": 0.8,
            "peak_process_memory_gb": 3.0,
        },
    }

    selection = select_embedding_model(reports)

    assert selection["selected"] == "multilingual-e5-base"
    assert selection["reason"] == "ndcg_tie_choose_lower_latency_and_memory"


def test_quality_gate_requires_all_six_reports() -> None:
    result = quality_gate({"bm25": {}})

    assert result["passed"] is False
    assert "hybrid_rerank" in result["missing"]


def test_candidate_pool_deduplicates_and_records_source_ranks() -> None:
    shared = record("labour_law", "shared")
    lexical_only = record("labour_law", "lexical")
    dense_only = record("labour_law", "dense")

    pooled = _pool_hits(
        {
            "bm25": [SearchHit(shared, 4.0), SearchHit(lexical_only, 3.0)],
            "bge-m3": [SearchHit(dense_only, 0.9), SearchHit(shared, 0.8)],
        }
    )

    assert len(pooled) == 3
    assert pooled[0]["record"].chunk_id == shared.chunk_id
    assert [source["system"] for source in pooled[0]["sources"]] == ["bm25", "bge-m3"]


def test_draft_relevance_only_marks_exact_legislation_article_as_high() -> None:
    exact = replace(
        record("labour_law", "İş Kanunu Madde 18"),
        primary_legislation_number="4857",
        legislation_numbers=("4857",),
        article_labels=("18",),
    )
    cited_elsewhere = replace(
        record("labour_law", "Başka karar"),
        document_type="court_decision",
        legislation_numbers=("4857",),
    )

    assert _draft_relevance(["4857:18-19"], exact) == 2
    assert _draft_relevance(["4857:18-19"], cited_elsewhere) == 0
    assert _draft_relevance(["Yargıtay"], cited_elsewhere) == 1
