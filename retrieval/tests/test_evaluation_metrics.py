from dataclasses import replace
from math import log2

import pytest

from beken_retrieval.evaluation import (
    EvaluationQuery,
    RelevanceLabel,
    evaluate,
    quality_gate,
    reference_relevance,
)
from beken_retrieval.models import ChunkRecord, SearchHit


def record(chunk_id="a", **changes):
    base = ChunkRecord(
        chunk_id=chunk_id,
        parse_id="parse",
        document_id="document",
        source_document_id="law-4857",
        domain_code="labour_law",
        corpus_version="v4",
        retrieval_scope_version="scope-v1",
        domain_role="core",
        document_type="law",
        title="4857 sayılı İş Kanunu",
        text="Fixture passage",
        section_type="article",
        primary_legislation_number="4857",
        article_labels=("18",),
    )
    return replace(base, **changes)


def query(query_id="q", labels=(), **changes):
    base = EvaluationQuery(query_id, query_id, "development", ("labour_law",), tuple(labels))
    return replace(base, **changes)


class StaticCoordinator:
    def __init__(self, results):
        self.results = results

    def search(self, text, **kwargs):
        # Deliberately ignore limit: the evaluator must enforce its own @10 cutoff.
        return [SearchHit(record(chunk_id), 1.0) for chunk_id in self.results.get(text, [])]


def test_recall_is_fraction_of_reviewed_relevant_chunks_not_hit_rate():
    labels = tuple(
        RelevanceLabel(key, grade, "reviewed")
        for key, grade in (
            ("a", 2),
            ("b", 1),
            ("c", 2),
            ("irrelevant", 0),
        )
    ) + (RelevanceLabel("pending", 2, "pending"),)
    report = evaluate(
        StaticCoordinator({"q": ["a", "irrelevant", "pending", "unjudged"]}),
        [query(labels=labels)],
        mode="bm25",
    )
    assert report["recall_at_10"] == pytest.approx(1 / 3)
    assert report["per_query"][0]["recall_at_10"] == pytest.approx(1 / 3)


def test_recall_averages_queries_not_raw_hit_counts():
    queries = [
        query("one", [RelevanceLabel("a", 2, "reviewed"), RelevanceLabel("b", 1, "reviewed")]),
        query("two", [RelevanceLabel("c", 2, "reviewed")], split="holdout"),
    ]
    report = evaluate(StaticCoordinator({"one": ["a"], "two": ["c"]}), queries, mode="bm25")
    assert report["recall_at_10"] == 0.75
    assert report["splits"]["development"]["recall_at_10"] == 0.5
    assert report["splits"]["holdout"]["recall_at_10"] == 1.0


def test_only_top_ten_results_count():
    report = evaluate(
        StaticCoordinator({"q": [f"noise-{i}" for i in range(10)] + ["a"]}),
        [query(labels=[RelevanceLabel("a", 2, "reviewed")])],
        mode="bm25",
    )
    assert report["recall_at_10"] == 0.0
    assert len(report["per_query"][0]["result_chunk_ids"]) == 10


def test_duplicate_hits_cannot_inflate_recall_or_ndcg():
    report = evaluate(
        StaticCoordinator({"q": ["a", "a"]}),
        [query(labels=[RelevanceLabel("a", 2, "reviewed")])],
        mode="bm25",
    )
    assert report["recall_at_10"] == 1.0
    assert report["ndcg_at_10"] == 1.0


def test_ndcg_keeps_graded_relevance():
    report = evaluate(
        StaticCoordinator({"q": ["b", "a"]}),
        [query(labels=[RelevanceLabel("a", 2, "reviewed"), RelevanceLabel("b", 1, "reviewed")])],
        mode="bm25",
    )
    assert report["ndcg_at_10"] == pytest.approx((1 + 3 / log2(3)) / (3 + 1 / log2(3)))


def test_pending_and_zero_relevance_queries_do_not_enter_benchmark():
    report = evaluate(
        StaticCoordinator({}),
        [
            query("pending", [RelevanceLabel("a", 2, "pending")]),
            query("negative", [RelevanceLabel("b", 0, "reviewed")]),
        ],
        mode="bm25",
    )
    assert report["eligible_queries"] == 0
    assert report["recall_at_10"] == 0.0


@pytest.mark.parametrize("limit", [0, 5, 20])
def test_at_ten_report_rejects_other_cutoffs(limit):
    with pytest.raises(ValueError, match="10"):
        evaluate(StaticCoordinator({}), [], mode="bm25", limit=limit)


def test_reports_identify_corrected_pooled_recall_definition():
    report = evaluate(StaticCoordinator({}), [], mode="bm25")
    assert report["metric_version"] == "retrieval-metrics-v2"
    assert report["recall_basis"] == "reviewed_positive_pool"


@pytest.mark.parametrize(
    "references,changes,expected",
    [
        (["4857:18-19"], {"article_labels": ("70",)}, 0),
        (["4857:18-19"], {"article_labels": ("19",)}, 2),
        (["4857:17,24,25"], {"article_labels": ("24",)}, 2),
        (["4857:Ek3"], {"article_labels": ("EK3",)}, 2),
        (["4857:35/A"], {"article_labels": ("35/A",)}, 2),
        (["4857:18-19"], {"article_labels": ("18/A",)}, 0),
        (["4857:18-19"], {"article_labels": ()}, 1),
        (["4857"], {}, 1),
        (["485:18"], {}, 0),
        (["4857:18"], {"primary_legislation_number": None}, 0),
        (["4857:18"], {"primary_legislation_number": "6356"}, 0),
        ([""], {}, 0),
        ([" 4857 : 18 "], {}, 2),
        (["İş Kanunu"], {"title": "İŞ KANUNU"}, 1),
        (
            ["4857:18"],
            {
                "document_type": "court_decision",
                "primary_legislation_number": None,
                "title": "4857 İş Kanunu madde 18 hakkında Yargıtay kararı",
                "legislation_numbers": ("4857",),
            },
            0,
        ),
        (["Yargıtay"], {"document_type": "court_decision"}, 1),
    ],
)
def test_draft_labels_require_source_and_article_match(references, changes, expected):
    assert reference_relevance(references, record(**changes)) == expected


def test_reference_order_cannot_hide_a_later_exact_match():
    item = record()
    assert reference_relevance(["4857:70", "4857:18"], item) == 2
    assert reference_relevance(["4857:18", "4857:70"], item) == 2
    assert reference_relevance(["4857", "4857:18"], item) == 2


def reports():
    return {
        name: {
            "metric_version": "retrieval-metrics-v2",
            "recall_basis": "reviewed_positive_pool",
            "eligible_queries": 100,
            "recall_at_10": 0.9,
            "ndcg_at_10": 0.85 if name == "hybrid_rerank" else 0.7,
            "p95_latency_seconds": 1.0,
            "peak_process_memory_gb": 2.0,
        }
        for name in (
            "bm25",
            "e5_vector",
            "bge_m3_vector",
            "e5_hybrid",
            "bge_m3_hybrid",
            "hybrid_rerank",
        )
    }


def test_quality_gate_rejects_legacy_hit_rate_reports():
    legacy = reports()
    legacy["bm25"].pop("metric_version")
    result = quality_gate(legacy)
    assert result["passed"] is False
    assert result["reason"] == "incompatible_metric_definition"


def test_quality_gate_accepts_consistent_corrected_metrics():
    assert quality_gate(reports())["passed"] is True
