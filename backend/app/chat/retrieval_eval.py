"""Measure the law search as a chat turn runs it: query planner first, then the search.

Each evaluation question that names a statute article among its expected references is
rewritten by the chat's query planner. The planned query and the planner's article hints
then go through the law search with the chat's settings (BM25 + BGE-M3, RRF, reranker,
25 results). A question is found at the first rank whose passage carries an expected
article.

Plans are cached in <out>/plans.jsonl, so a rerun calls no model and measures only the
search; delete the file to plan again. A failed planner call is not cached: that question
is searched with its own words, as the chat would, and is planned again on the next run.

    python -m app.chat.retrieval_eval --queries evals/labour_law/queries.v1.jsonl --out report/

The defaults are the measurements of ADR 0010 and 0011: 6 questions per topic, article
hints on. --no-hints measures the search without the hints.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from beken_retrieval.coordinator import SearchMode
from beken_retrieval.evaluation import reference_relevance
from beken_retrieval.models import SearchFilters, SearchHit

from app.chat.query import derive_retrieval_query, plan_query
from app.llm.provider import LLMProvider, PermanentLLMError, TransientLLMError

DOMAIN = "labour_law"
RESULT_LIMIT = 25
TOP_K = (1, 3, 8, 25)
_ARTICLE_REF = re.compile(r"^\d+:\S")


def select_questions(items: list[dict], *, per_topic: int) -> list[dict]:
    """Questions whose expected references name a statute article: the first `per_topic`
    of each topic in file order, or all of them when per_topic is 0."""
    taken: dict[str, int] = defaultdict(int)
    chosen = []
    for item in items:
        if not any(_ARTICLE_REF.match(ref) for ref in item.get("expected_refs") or ()):
            continue
        if per_topic and taken[item["topic"]] >= per_topic:
            continue
        taken[item["topic"]] += 1
        chosen.append(item)
    return chosen


def first_match(hits: list[SearchHit], refs: list[str]) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if reference_relevance(refs, hit.record) == 2:
            return rank
    return None


@dataclass
class FailureCounter:
    """Counts failed planner calls; the planner itself falls back to the question silently."""

    provider: LLMProvider
    failures: int = 0

    async def structured_output(self, **arguments):
        try:
            return await self.provider.structured_output(**arguments)
        except (TransientLLMError, PermanentLLMError):
            self.failures += 1
            raise


def load_plans(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    # A question planned again after its text changed appears twice; the last row wins.
    return {row["query_id"]: row for row in rows}


async def plan_questions(
    questions: list[dict], *, provider: LLMProvider, model: str, cache: Path
) -> dict[str, dict[str, Any]]:
    plans = load_plans(cache)
    counter = FailureCounter(provider)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("a", encoding="utf-8") as out:
        for item in questions:
            cached = plans.get(item["query_id"])
            if cached and cached["query"] == item["query"]:
                continue
            failures = counter.failures
            plan = await plan_query(counter, model=model, message=item["query"], history=[])
            row = {
                "query_id": item["query_id"],
                "query": item["query"],
                "search_query": plan.search_query or derive_retrieval_query(item["query"]),
                "articles": [[hint.law, hint.article] for hint in plan.articles],
            }
            if counter.failures > failures:
                row["planner_failed"] = True
            else:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
            plans[item["query_id"]] = row
    return plans


def search_questions(
    questions: list[dict], plans: dict[str, dict[str, Any]], *, coordinator, hints: bool
) -> list[dict[str, Any]]:
    rows = []
    for item in questions:
        plan = plans[item["query_id"]]
        articles = [(law, article) for law, article in plan["articles"]] if hints else []
        started = time.monotonic()
        # The law search of GroundedChatService._retrieve.
        hits = coordinator.search(
            plan["search_query"],
            domains=(DOMAIN,),
            mode=SearchMode.HYBRID_RERANK.value,
            filters=SearchFilters(domain_roles=("core", "supplemental")),
            limit=RESULT_LIMIT,
            articles=articles,
        )
        rank = first_match(hits, item["expected_refs"])
        top = hits[0].record if hits else None
        rows.append(
            {
                "query_id": item["query_id"],
                "topic": item["topic"],
                "query": item["query"],
                "expected_refs": item["expected_refs"],
                "search_query": plan["search_query"],
                "articles": [list(article) for article in articles],
                "planner_failed": plan.get("planner_failed", False),
                "rank": rank,
                "top_result": f"{top.title} > {' > '.join(top.breadcrumb[-2:])}" if top else None,
                "seconds": round(time.monotonic() - started, 1),
            }
        )
        print(f"{item['query_id']}: rank {rank or '-'}", flush=True)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    summary: dict[str, Any] = {"questions": count}
    for k in TOP_K:
        found = sum(1 for row in rows if row["rank"] is not None and row["rank"] <= k)
        summary[f"top_{k}"] = found
        summary[f"top_{k}_share"] = round(found / count, 3) if count else 0.0
    summary["missed"] = [row["query_id"] for row in rows if row["rank"] is None]
    summary["planner_failures"] = sum(1 for row in rows if row["planner_failed"])
    summary["mean_seconds"] = round(mean(row["seconds"] for row in rows), 1) if rows else 0.0
    return summary


async def run(queries: Path, out_dir: Path, *, per_topic: int, hints: bool) -> dict[str, Any]:
    from app.api.search import _load_search_coordinator
    from app.chat.answer_eval import PacedProvider
    from app.core.config import get_settings
    from app.llm.gemini import get_llm_provider

    settings = get_settings()
    items = [
        json.loads(line) for line in queries.read_text(encoding="utf-8").splitlines() if line
    ]
    questions = select_questions(items, per_topic=per_topic)
    provider = PacedProvider(
        get_llm_provider(), per_minute={settings.gemini_query_model: 12}
    )
    plans = await plan_questions(
        questions,
        provider=provider,
        model=settings.gemini_query_model,
        cache=out_dir / "plans.jsonl",
    )
    rows = search_questions(
        questions, plans, coordinator=_load_search_coordinator(), hints=hints
    )
    report = {
        "settings": {
            "queries": str(queries),
            "per_topic": per_topic,
            "hints": hints,
            "planner_model": settings.gemini_query_model,
        },
        "summary": summarize(rows),
        "rows": rows,
    }
    name = "report.json" if hints else "report-no-hints.json"
    (out_dir / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--per-topic", type=int, default=6, help="questions per topic; 0 takes all of them"
    )
    parser.add_argument("--no-hints", action="store_true", help="search without article hints")
    arguments = parser.parse_args()
    report = asyncio.run(
        run(
            arguments.queries,
            arguments.out,
            per_topic=arguments.per_topic,
            hints=not arguments.no_hints,
        )
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
