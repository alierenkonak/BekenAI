from __future__ import annotations

import pytest

from app.chat import answer_eval
from app.chat.answer_eval import PacedProvider, answer_metrics, judge_order, summarize
from app.chat.grounded import CompletedAnswer


def _result(verifications: list[str], channels: list[str], *, fallback=False) -> CompletedAnswer:
    sentences = [
        {"id": f"S{i}", "text": "x", "source_ids": ["S"] if v != "plain" else [], "verification": v}
        for i, v in enumerate(verifications, 1)
    ]
    return CompletedAnswer(
        content="metin",
        structured_content={"blocks": [{"kind": "paragraph", "sentences": sentences}]},
        citations=[{"source_channel": channel} for channel in channels],
        answer_status="answered",
        actual_model="m",
        fallback_used=fallback,
        verifier_model="v",
        input_tokens=10,
        output_tokens=100,
        latency_ms=1,
        corpus_versions={},
        index_versions={},
        thinking_tokens=50,
    )


def test_metrics_count_sentences_verification_and_channels() -> None:
    metrics = answer_metrics(
        _result(["plain", "verified", "partial", "unverified"], ["primary", "file", "primary"]),
        12.34,
    )

    assert metrics["seconds"] == 12.3
    assert (metrics["sentences"], metrics["cited_sentences"]) == (4, 3)
    assert (metrics["verified"], metrics["partial"], metrics["unverified"]) == (1, 1, 1)
    assert (metrics["citations"], metrics["primary_citations"]) == (3, 2)
    assert metrics["thinking_tokens"] == 50


def test_summary_compares_variants() -> None:
    def row(variant: str, result: CompletedAnswer, seconds: float) -> dict:
        return {"variant": variant, **answer_metrics(result, seconds)}

    rows = [
        row("before", _result(["verified", "unverified"], ["primary"]), 10),
        row("after", _result(["verified", "verified"], ["primary"]), 20),
        row("after", _result(["plain"], [], fallback=True), 30),
    ]

    summary = summarize(rows)

    assert summary["before"]["unverified_sentences"] == 1
    assert summary["before"]["verified_share_of_cited"] == 0.5
    assert summary["after"]["verified_share_of_cited"] == 1.0
    assert summary["after"]["mean_seconds"] == 25.0
    assert summary["after"]["fallbacks"] == 1


def test_judge_order_is_stable_and_alternates() -> None:
    orders = {judge_order(f"A{index:02d}") for index in range(1, 11)}
    assert orders == {("before", "after"), ("after", "before")}
    assert judge_order("A01") == judge_order("A01")


@pytest.mark.asyncio
async def test_paced_provider_waits_once_the_minute_budget_is_used(monkeypatch) -> None:
    clock = {"now": 0.0}
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(answer_eval.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(answer_eval.asyncio, "sleep", fake_sleep)

    class Inner:
        async def structured_output(self, **_):
            return "ok"

    paced = PacedProvider(Inner(), per_minute={"flash": 2})
    for _ in range(3):
        await paced.structured_output(model="flash", prompt="p", schema=None)

    assert len(waits) == 1 and waits[0] == pytest.approx(60.5)
