"""Compare answer settings on a fixed question set, with the same evidence for each.

Each question is planned and searched once; every variant then answers from that
evidence, so differences come only from the model settings under test. A blind
pairwise judge (the primary model, order alternated per question) adds a quality
signal on top of the counted metrics. Runs within free-tier request rates.

    python -m app.chat.answer_eval --questions evals/labour_law/answers.v1.jsonl --out report/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.chat.grounded import CompletedAnswer, GroundedChatService
from app.core.config import Settings
from app.llm.provider import (
    LLMProvider,
    PermanentLLMError,
    StructuredResult,
    TransientLLMError,
)

# Settings as they were before this tuning, and as they are now.
VARIANTS: dict[str, dict[str, Any]] = {
    "before": {
        "gemini_answer_thinking_level": None,
        "gemini_verifier_temperature": None,
        "gemini_max_output_tokens": 8_192,
    },
    "after": {},
}


class JudgeVerdict(BaseModel):
    winner: Literal["A", "B", "tie"]
    reason: str = Field(max_length=600)


@dataclass
class PacedProvider:
    """Wraps a provider so no model exceeds its requests-per-minute budget."""

    provider: LLMProvider
    per_minute: dict[str, int]
    default_per_minute: int = 10
    _calls: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    async def structured_output(self, *, model: str, prompt: str, schema, **options):
        budget = self.per_minute.get(model, self.default_per_minute)
        while True:
            now = time.monotonic()
            recent = [stamp for stamp in self._calls[model] if now - stamp < 60]
            self._calls[model] = recent
            if len(recent) < budget:
                break
            await asyncio.sleep(60 - (now - recent[0]) + 0.5)
        self._calls[model].append(time.monotonic())
        return await self.provider.structured_output(
            model=model, prompt=prompt, schema=schema, **options
        )


def answer_metrics(result: CompletedAnswer, seconds: float) -> dict[str, Any]:
    sentences = [
        sentence
        for block in result.structured_content.get("blocks", [])
        for sentence in block["sentences"]
    ]
    verification = Counter(sentence["verification"] for sentence in sentences)
    channels = Counter(citation["source_channel"] for citation in result.citations)
    return {
        "seconds": round(seconds, 1),
        "model": result.actual_model,
        "fallback_used": result.fallback_used,
        "answer_status": result.answer_status,
        "output_tokens": result.output_tokens,
        "thinking_tokens": result.thinking_tokens,
        "sentences": len(sentences),
        "cited_sentences": sum(1 for sentence in sentences if sentence["source_ids"]),
        "verified": verification["verified"],
        "partial": verification["partial"],
        "unverified": verification["unverified"],
        "citations": len(result.citations),
        "primary_citations": channels["primary"],
        "doctrine_citations": channels["doctrine"],
        "characters": len(result.content),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for variant in sorted({row["variant"] for row in rows}):
        items = [row for row in rows if row["variant"] == variant]

        def average(key: str, items: list[dict[str, Any]] = items) -> float:
            values = [row[key] for row in items if row.get(key) is not None]
            return round(mean(values), 2) if values else 0.0

        cited = sum(row["cited_sentences"] for row in items)
        summary[variant] = {
            "answers": len(items),
            "mean_seconds": average("seconds"),
            "mean_output_tokens": average("output_tokens"),
            "mean_thinking_tokens": average("thinking_tokens"),
            "mean_sentences": average("sentences"),
            "mean_citations": average("citations"),
            "mean_primary_citations": average("primary_citations"),
            "unverified_sentences": sum(row["unverified"] for row in items),
            "verified_share_of_cited": round(
                sum(row["verified"] for row in items) / cited, 3
            )
            if cited
            else 0.0,
            "fallbacks": sum(1 for row in items if row["fallback_used"]),
        }
    return summary


def judge_order(question_id: str) -> tuple[str, str]:
    """Alternate which variant is shown first, deterministically per question."""
    return ("before", "after") if zlib.crc32(question_id.encode()) % 2 else ("after", "before")


async def judge(
    provider: LLMProvider, model: str, question: str, first: str, second: str
) -> JudgeVerdict:
    prompt = f"""İki cevabı, bir iş hukuku avukatının gözünden karşılaştır. Soruya doğrudan
cevap vermesi, sorunun her parçasını karşılaması, açıklığı, akıcılığı ve hukuki
dayanağının açıkça belirtilmesi önemli. Uzunluk tek başına üstünlük değildir.
Hangisi daha iyi? A, B ya da tie; kısa gerekçe yaz.

<soru>{question}</soru>
<cevap_A>{first}</cevap_A>
<cevap_B>{second}</cevap_B>"""
    result: StructuredResult = await provider.structured_output(
        model=model, prompt=prompt, schema=JudgeVerdict, temperature=0.0
    )
    verdict = result.value
    if not isinstance(verdict, JudgeVerdict):
        raise ValueError("invalid_judge_output")
    return verdict


async def run(questions_path: Path, out_dir: Path) -> dict[str, Any]:
    from app.api.search import _load_search_coordinator
    from app.core.config import get_settings
    from app.llm.gemini import get_llm_provider

    settings = get_settings()
    provider = PacedProvider(
        get_llm_provider(),
        per_minute={
            settings.gemini_primary_model: 4,
            settings.gemini_fallback_model: 12,
            settings.gemini_claim_support_model: 12,
            settings.gemini_query_model: 12,
        },
    )
    coordinator = _load_search_coordinator()
    services = {
        name: GroundedChatService(
            coordinator, provider, Settings.model_validate({**settings.model_dump(), **changes})
        )
        for name, changes in VARIANTS.items()
    }
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows: list[dict[str, Any]] = []
    answers: dict[str, dict[str, str]] = {}
    verdicts: list[dict[str, Any]] = []
    for item in questions:
        turn = await services["after"].prepare(
            message=item["question"],
            retrieval_query=item["question"][:500],
            domain="labour_law",
            history=item.get("history", []),
        )
        answers[item["id"]] = {}
        for name, service in services.items():
            started = time.monotonic()
            result = await service.respond(turn)
            rows.append(
                {
                    "question_id": item["id"],
                    "variant": name,
                    **answer_metrics(result, time.monotonic() - started),
                }
            )
            answers[item["id"]][name] = result.content
        first, second = judge_order(item["id"])
        try:
            verdict = await judge(
                provider,
                settings.gemini_primary_model,
                item["question"],
                answers[item["id"]][first],
                answers[item["id"]][second],
            )
            winner = {"A": first, "B": second}.get(verdict.winner, "tie")
            reason = verdict.reason
        except (TransientLLMError, PermanentLLMError, ValueError) as exc:
            # A quota hit on the judge should not throw away the measured answers.
            winner, reason = "error", f"{type(exc).__name__}: {exc}"
        verdicts.append({"question_id": item["id"], "winner": winner, "reason": reason})
        print(f"{item['id']}: judge prefers {winner}", flush=True)

    report = {
        "summary": summarize(rows),
        "judge": dict(Counter(verdict["winner"] for verdict in verdicts)),
        "rows": rows,
        "verdicts": verdicts,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# Cevap karşılaştırması", ""]
    for item in questions:
        verdict = next(v for v in verdicts if v["question_id"] == item["id"])
        lines += [f"## {item['id']} · {item['question']}", ""]
        lines += [f"Hakem: **{verdict['winner']}**, {verdict['reason']}", ""]
        for name in VARIANTS:
            lines += [f"### {name}", "", answers[item["id"]][name], ""]
    (out_dir / "answers.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    report = asyncio.run(run(arguments.questions, arguments.out))
    print(json.dumps({"summary": report["summary"], "judge": report["judge"]}, indent=2))


if __name__ == "__main__":
    main()
