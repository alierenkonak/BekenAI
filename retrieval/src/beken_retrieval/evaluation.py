from __future__ import annotations

import json
import math
import resource
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beken_retrieval.coordinator import DomainSearchCoordinator
from beken_retrieval.models import SearchFilters

METRIC_VERSION = "retrieval-metrics-v2"
RECALL_BASIS = "reviewed_positive_pool"


@dataclass(frozen=True)
class RelevanceLabel:
    chunk_id: str
    relevance: int
    review_status: str


@dataclass(frozen=True)
class EvaluationQuery:
    query_id: str
    query: str
    split: str
    domains: tuple[str, ...]
    labels: tuple[RelevanceLabel, ...]
    coverage_gap: bool = False


def load_queries(path: Path) -> list[EvaluationQuery]:
    queries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        queries.append(
            EvaluationQuery(
                query_id=str(payload["query_id"]),
                query=str(payload["query"]),
                split=str(payload["split"]),
                domains=tuple(payload.get("domains") or ("labour_law",)),
                labels=tuple(
                    RelevanceLabel(
                        chunk_id=str(label["chunk_id"]),
                        relevance=int(label["relevance"]),
                        review_status=str(label.get("review_status") or "pending"),
                    )
                    for label in payload.get("labels") or ()
                ),
                coverage_gap=bool(payload.get("coverage_gap", False)),
            )
        )
    return queries


def reviewed_queries(queries: list[EvaluationQuery]) -> list[EvaluationQuery]:
    return [
        query
        for query in queries
        if query.split in {"development", "holdout"}
        and not query.coverage_gap
        and any(label.relevance > 0 and label.review_status == "reviewed" for label in query.labels)
    ]


def _dcg(relevances: list[int]) -> float:
    return sum(
        ((2**relevance) - 1) / math.log2(rank + 1)
        for rank, relevance in enumerate(relevances, start=1)
    )


def _peak_memory_gb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024**3 if __import__("sys").platform == "darwin" else 1024**2
    return value / divisor


def _metric_summary(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    latencies = sorted(float(row["latency_seconds"]) for row in rows)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    return {
        "eligible_queries": len(rows),
        "recall_at_10": statistics.fmean(float(row["recall_at_10"]) for row in rows)
        if rows
        else 0.0,
        "ndcg_at_10": statistics.fmean(float(row["ndcg_at_10"]) for row in rows) if rows else 0.0,
        "p95_latency_seconds": latencies[p95_index] if latencies else 0.0,
    }


def evaluate(
    coordinator: DomainSearchCoordinator,
    queries: list[EvaluationQuery],
    *,
    mode: str,
    limit: int = 10,
) -> dict[str, Any]:
    if limit != 10:
        raise ValueError("This evaluator reports @10 metrics; limit must be 10")
    eligible = reviewed_queries(queries)
    per_query: list[dict[str, Any]] = []
    for item in eligible:
        started = time.perf_counter()
        hits = coordinator.search(
            item.query,
            domains=item.domains,
            mode=mode,
            filters=SearchFilters(),
            limit=limit,
        )
        latency = time.perf_counter() - started
        relevance = {
            label.chunk_id: label.relevance
            for label in item.labels
            if label.review_status == "reviewed"
        }
        result_ids = [hit.record.chunk_id for hit in hits[:limit]]
        # Relevant means a reviewed grade of 1 or 2. This denominator describes
        # the judged candidate pool, not unknown relevant passages in the corpus.
        relevant_ids = {chunk_id for chunk_id, grade in relevance.items() if grade > 0}
        recall = len(set(result_ids) & relevant_ids) / len(relevant_ids) if relevant_ids else 0.0
        seen: set[str] = set()
        ranked = []
        for chunk_id in result_ids:
            # A repeated result occupies a rank but cannot earn relevance twice.
            ranked.append(relevance.get(chunk_id, 0) if chunk_id not in seen else 0)
            seen.add(chunk_id)
        ideal = sorted(relevance.values(), reverse=True)[:limit]
        ndcg = _dcg(ranked) / _dcg(ideal) if ideal and _dcg(ideal) else 0.0
        per_query.append(
            {
                "query_id": item.query_id,
                "split": item.split,
                "recall_at_10": recall,
                "ndcg_at_10": ndcg,
                "latency_seconds": latency,
                "result_chunk_ids": result_ids,
            }
        )
    summary = _metric_summary(per_query)
    return {
        "metric_version": METRIC_VERSION,
        "recall_basis": RECALL_BASIS,
        "mode": mode,
        "total_queries": len(queries),
        **summary,
        "peak_process_memory_gb": _peak_memory_gb(),
        "splits": {
            split: _metric_summary([row for row in per_query if row["split"] == split])
            for split in ("development", "holdout")
        },
        "per_query": per_query,
    }


def select_embedding_model(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidates = {
        "multilingual-e5-base": reports["e5_vector"],
        "bge-m3": reports["bge_m3_vector"],
    }
    e5_ndcg = float(candidates["multilingual-e5-base"]["ndcg_at_10"])
    bge_ndcg = float(candidates["bge-m3"]["ndcg_at_10"])
    if abs(e5_ndcg - bge_ndcg) < 0.01:
        selected = min(
            candidates,
            key=lambda name: (
                float(candidates[name]["p95_latency_seconds"]),
                float(candidates[name]["peak_process_memory_gb"]),
                name,
            ),
        )
        reason = "ndcg_tie_choose_lower_latency_and_memory"
    else:
        selected = max(
            candidates,
            key=lambda name: (float(candidates[name]["ndcg_at_10"]), name),
        )
        reason = "higher_ndcg_at_10"
    return {
        "selected": selected,
        "reason": reason,
        "ndcg_difference": abs(e5_ndcg - bge_ndcg),
    }


def quality_gate(
    reports: dict[str, dict[str, Any]],
    *,
    minimum_queries: int = 100,
) -> dict[str, Any]:
    required = {
        "bm25",
        "e5_vector",
        "bge_m3_vector",
        "e5_hybrid",
        "bge_m3_hybrid",
        "hybrid_rerank",
    }
    missing = sorted(required.difference(reports))
    if missing:
        return {"passed": False, "reason": "missing_reports", "missing": missing}
    incompatible = sorted(
        name
        for name in required
        if reports[name].get("metric_version") != METRIC_VERSION
        or reports[name].get("recall_basis") != RECALL_BASIS
    )
    if incompatible:
        return {
            "passed": False,
            "reason": "incompatible_metric_definition",
            "incompatible_reports": incompatible,
        }
    final = reports["hybrid_rerank"]
    baseline_ndcg = max(
        reports[name]["ndcg_at_10"] for name in ("bm25", "e5_vector", "bge_m3_vector")
    )
    checks = {
        "reviewed_queries": final["eligible_queries"] >= minimum_queries,
        "recall_at_10": final["recall_at_10"] >= 0.80,
        "ndcg_delta": final["ndcg_at_10"] >= baseline_ndcg + 0.02,
        "p95_latency": final["p95_latency_seconds"] <= 3.0,
        "peak_memory": final["peak_process_memory_gb"] <= 6.0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "embedding_selection": select_embedding_model(reports),
        "baseline_ndcg_at_10": baseline_ndcg,
        "final_ndcg_at_10": final["ndcg_at_10"],
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
