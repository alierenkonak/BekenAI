from __future__ import annotations

import json
from uuid import uuid4

import pytest
from beken_retrieval.models import ChunkRecord, SearchHit

from app.chat.retrieval_eval import (
    plan_questions,
    search_questions,
    select_questions,
    summarize,
)
from app.llm.models import ArticleHint, QueryPlan
from app.llm.provider import StructuredResult, TransientLLMError


def question(query_id: str, topic: str, refs: list[str], query: str = "Soru?") -> dict:
    return {"query_id": query_id, "topic": topic, "query": query, "expected_refs": refs}


def hit(law: str, article: str, *, title: str = "İş Kanunu") -> SearchHit:
    record = ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id="fixture",
        domain_code="labour_law",
        corpus_version="labour-law-pilot-v4",
        retrieval_scope_version="scope-v1",
        domain_role="core",
        document_type="law",
        title=title,
        text="Metin.",
        section_type="article",
        breadcrumb=(title, f"Madde {article}"),
        primary_legislation_number=law,
        article_labels=(article,),
    )
    return SearchHit(record=record, score=1.0)


class PlanningProvider:
    def __init__(self, plan: QueryPlan | Exception) -> None:
        self.plan = plan
        self.calls = 0

    async def structured_output(self, *, model: str, prompt: str, schema, **options):
        self.calls += 1
        if isinstance(self.plan, Exception):
            raise self.plan
        return StructuredResult(value=self.plan, model=model)


class RecordingCoordinator:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls: list[dict] = []

    def search(self, query: str, **options):
        self.calls.append({"query": query, **options})
        return self.hits


PLAN = QueryPlan(
    intent="legal",
    search_query="savunma alınmadan fesih geçerli fesih",
    articles=[ArticleHint(law="4857", article="19")],
)


def test_selects_article_questions_up_to_the_topic_limit() -> None:
    items = [
        question("L1", "fesih", ["4857:18"]),
        question("L2", "fesih", ["Yargıtay"]),
        question("L3", "fesih", ["6098"]),
        question("L4", "fesih", ["6098", "4857:Ek3"]),
        question("L5", "fesih", ["4857:25"]),
        question("L6", "usul", ["7036:3"]),
    ]

    assert [item["query_id"] for item in select_questions(items, per_topic=2)] == [
        "L1",
        "L4",
        "L6",
    ]
    assert len(select_questions(items, per_topic=0)) == 4


@pytest.mark.asyncio
async def test_plans_are_cached_and_a_changed_question_is_planned_again(tmp_path) -> None:
    cache = tmp_path / "plans.jsonl"
    questions = [question("L1", "fesih", ["4857:19"]), question("L2", "fesih", ["4857:18"])]
    provider = PlanningProvider(PLAN)

    plans = await plan_questions(questions, provider=provider, model="m", cache=cache)
    again = await plan_questions(questions, provider=provider, model="m", cache=cache)
    questions[1]["query"] = "Yeni soru?"
    changed = await plan_questions(questions, provider=provider, model="m", cache=cache)

    assert provider.calls == 3
    assert plans["L1"]["search_query"] == PLAN.search_query
    assert plans["L1"]["articles"] == [["4857", "19"]]
    assert again == plans
    assert changed["L2"]["query"] == "Yeni soru?"
    assert len(cache.read_text(encoding="utf-8").splitlines()) == 3


@pytest.mark.asyncio
async def test_a_failed_plan_searches_the_question_and_is_not_cached(tmp_path) -> None:
    cache = tmp_path / "plans.jsonl"
    questions = [question("L1", "fesih", ["4857:19"], query="Savunmam alınmadan çıkarıldım?")]

    plans = await plan_questions(
        questions,
        provider=PlanningProvider(TransientLLMError("503")),
        model="m",
        cache=cache,
    )

    assert plans["L1"]["planner_failed"] is True
    assert plans["L1"]["search_query"] == "Savunmam alınmadan çıkarıldım?"
    assert plans["L1"]["articles"] == []
    assert cache.read_text(encoding="utf-8") == ""


def test_search_passes_hints_and_ranks_the_first_expected_article() -> None:
    questions = [question("L1", "fesih", ["4857:19"]), question("L2", "fesih", ["4857:Ek3"])]
    plans = {
        "L1": {"search_query": "q1", "articles": [["4857", "19"]]},
        "L2": {"search_query": "q2", "articles": []},
    }
    coordinator = RecordingCoordinator([hit("4857", "18"), hit("5510", "19"), hit("4857", "19")])

    rows = search_questions(questions, plans, coordinator=coordinator, hints=True)
    without = search_questions(questions, plans, coordinator=coordinator, hints=False)

    assert [row["rank"] for row in rows] == [3, None]
    assert coordinator.calls[0]["articles"] == [("4857", "19")]
    assert coordinator.calls[0]["limit"] == 25
    assert coordinator.calls[2]["articles"] == []
    assert without[0]["articles"] == []
    assert rows[0]["top_result"] == "İş Kanunu > İş Kanunu > Madde 18"
    json.dumps(rows, ensure_ascii=False)


def test_summary_counts_ranks_and_misses() -> None:
    rows = [
        {"query_id": "L1", "rank": 1, "planner_failed": False, "seconds": 10.0},
        {"query_id": "L2", "rank": 5, "planner_failed": False, "seconds": 20.0},
        {"query_id": "L3", "rank": 20, "planner_failed": True, "seconds": 30.0},
        {"query_id": "L4", "rank": None, "planner_failed": False, "seconds": 40.0},
    ]

    summary = summarize(rows)

    assert (summary["top_1"], summary["top_3"], summary["top_8"], summary["top_25"]) == (
        1,
        1,
        2,
        3,
    )
    assert summary["top_25_share"] == 0.75
    assert summary["missed"] == ["L4"]
    assert summary["planner_failures"] == 1
    assert summary["mean_seconds"] == 25.0
