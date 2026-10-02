from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from beken_retrieval.models import ChunkRecord, SearchHit

from app.chat.grounded import GroundedChatService
from app.chat.research import MAX_FOLLOW_UPS, MAX_SUB_QUESTIONS, DeepResearchService
from app.core.config import Settings
from app.files.retrieval import PrivateHit, PrivateScope
from app.llm.models import (
    AnswerBlock,
    AnswerSentence,
    ChatAnswer,
    ResearchGap,
    ResearchGaps,
    ResearchPlan,
    ResearchQuestion,
    SupportAssessment,
    SupportReport,
)
from app.llm.provider import StructuredResult
from app.web.search import WebHit

SCOPE = PrivateScope(workspace_id=uuid4(), conversation_id=uuid4(), case_id=uuid4())
QUESTION = "Performans düşüklüğüyle fesihte savunma ve ispat yükü nasıl işler?"


def law_hit(text: str, article: str, *, decision: bool = False) -> SearchHit:
    record = ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id="fixture",
        domain_code="labour_law",
        corpus_version="labour-law-pilot-v4",
        retrieval_scope_version="scope-v1",
        domain_role="core",
        document_type="court_decision" if decision else "law",
        title="Yargıtay 9. Hukuk Dairesi, E. 2022/1, K. 2022/2" if decision else "İş Kanunu",
        text=text,
        section_type="article",
        breadcrumb=() if decision else (f"Madde {article}",),
        page_number=1,
        case_number="2022/1" if decision else None,
        decision_number="2022/2" if decision else None,
        document_date=date(2022, 5, 1) if decision else date(2003, 6, 10),
        legislation_numbers=() if decision else ("4857",),
        article_labels=() if decision else (article,),
    )
    return SearchHit(record=record, score=1.0, rank=1)


VALID = law_hit("Fesih geçerli bir sebebe dayanmalıdır.", "18")
DEFENCE = law_hit("Verimle ilgili fesihte savunma alınmalıdır.", "19")
# The decision rests on article 20, which no search found: it is looked up. Its closing
# formula cites the appeal articles of the procedure code, which are not followed.
CITING = law_hit(
    "4857 sayılı İş Kanunu'nun 20. maddesine göre feshin geçerli sebebe dayandığını işveren "
    "ispat eder. 6100 sayılı HMK'nın 369/1 ve 371. maddeleri uyarınca BOZULMASINA.",
    "",
    decision=True,
)
PROOF = law_hit("Feshin geçerli sebebe dayandığını ispat yükü işverene aittir.", "20")
# Doctrine is searched for every research, once, with the question itself.
DOCTRINE = SearchHit(
    record=ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id="course-note",
        domain_code="labour_law",
        corpus_version="labour-law-doctrine-v1",
        retrieval_scope_version="labour-law-doctrine-v1",
        domain_role="supplemental",
        source_kind="doctrine",
        document_type="course_note",
        title="İş Hukuku Ders Notu",
        text="Öğretide verim düşüklüğü, işçinin yeterliliğinden kaynaklanan bir sebep sayılır.",
        section_type="paragraph",
        breadcrumb=(),
        page_number=12,
    ),
    score=1.0,
    rank=1,
)
CRITERIA = law_hit("Performans ölçütü objektif ve herkese eşit uygulanmalıdır.", "", decision=True)

PLAN = ResearchPlan(
    sub_questions=[
        ResearchQuestion(question="Geçerli fesih şartları", search_query="geçerli fesih şartları"),
        ResearchQuestion(question="Savunma alınması", search_query="savunma alınması verim fesih"),
        ResearchQuestion(question="İspat yükü", search_query="feshin ispat yükü"),
        # The same part twice is kept once.
        ResearchQuestion(question="savunma  alınması", search_query="savunma hakkı"),
    ],
    web_query="performans düşüklüğü fesih savunma ispat",
)
GAPS = ResearchGaps(
    follow_ups=[
        ResearchGap(serves=2, search_query="performans ölçütü objektif"),
        # A repeated search runs once.
        ResearchGap(serves=2, search_query="performans ölçütü  objektif"),
    ]
)
REPORT = ChatAnswer(
    answer_status="answered",
    blocks=[
        AnswerBlock(
            kind="paragraph",
            sentences=[
                AnswerSentence(text="İspat yükü işverendedir.", source_ids=["SOURCE_PRIMARY_05"]),
            ],
        ),
        AnswerBlock(kind="heading", sentences=[AnswerSentence(text="Savunma alınması")]),
        AnswerBlock(
            kind="bullets",
            sentences=[
                AnswerSentence(text="Savunma alınmalıdır.", source_ids=["SOURCE_PRIMARY_03"]),
            ],
        ),
    ],
)


class FakeCoordinator:
    def __init__(self, *, article_error: Exception | None = None) -> None:
        self.registry = SimpleNamespace(get=lambda *_: SimpleNamespace(index_version="idx"))
        self.searches: list[tuple[str, str]] = []
        self.article_requests: list[list[tuple[str, str]]] = []
        self.article_error = article_error
        self.results = {
            "geçerli fesih şartları": [VALID, CITING],
            "savunma alınması verim fesih": [DEFENCE],
            "feshin ispat yükü": [CITING],
            "performans ölçütü objektif": [CRITERIA],
        }

    def search(self, query: str, **kwargs):
        channel = kwargs.get("channel", "primary")
        self.searches.append((query, channel))
        return [DOCTRINE] if channel == "doctrine" else self.results.get(query, [])

    def article_hits(self, references, **kwargs):
        self.article_requests.append(list(references))
        if self.article_error:
            raise self.article_error
        return [PROOF] if ("4857", "20") in references else []


class FakeProvider:
    def __init__(self, plan: ResearchPlan = PLAN, gaps: ResearchGaps = GAPS) -> None:
        self.plan = plan
        self.gaps = gaps
        self.calls: list[str] = []
        self.prompts: dict[str, str] = {}

    async def structured_output(self, *, model: str, prompt: str, schema, **_options):
        self.calls.append(f"{model}:{schema.__name__}")
        self.prompts[schema.__name__] = prompt
        if schema is ResearchPlan:
            return StructuredResult(value=self.plan, model=model)
        if schema is ResearchGaps:
            return StructuredResult(value=self.gaps, model=model)
        if schema is ChatAnswer:
            return StructuredResult(value=REPORT, model=model, input_tokens=9, output_tokens=3)
        pairs = json.loads(prompt[prompt.index("[") :])
        return StructuredResult(
            value=SupportReport(
                assessments=[
                    SupportAssessment(
                        claim_id=pair["claim_id"],
                        source_id=pair["source_id"],
                        status="supported",
                        reason="fixture",
                    )
                    for pair in pairs
                ]
            ),
            model=model,
        )


class FakeFiles:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, scope: PrivateScope) -> list[PrivateHit]:
        self.queries.append(query)
        return [
            PrivateHit(
                chunk_id=uuid4(),
                file_id=uuid4(),
                file_name="Dava Dilekçesi.pdf",
                chunk_index=0,
                text=f"Dosyada {query} hakkında bir iddia.",
                section_title="AÇIKLAMALAR",
                page_start=2,
                page_end=2,
                paragraph_start=1,
                paragraph_end=1,
                score=0.9,
            )
        ]


class FakeWebSearch:
    index_version = "tavily-advanced"

    def __init__(self, hits: list[WebHit]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    async def search(self, query: str) -> list[WebHit]:
        self.queries.append(query)
        return self.hits


def settings() -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key="test",
        gemini_primary_model="gemini-primary",
        gemini_fallback_model="gemini-fallback",
        gemini_claim_support_model="gemini-support",
        gemini_query_model="gemini-query",
        gemini_research_model="gemini-research",
    )


def research(provider=None, *, coordinator=None, files=None, web=None):
    provider = provider or FakeProvider()
    coordinator = coordinator or FakeCoordinator()
    chat = GroundedChatService(
        coordinator, provider, settings(), private_retriever=files, web_search=web
    )
    return DeepResearchService(chat, settings()), provider, coordinator


async def run(service: DeepResearchService, **overrides):
    values = {
        "message": QUESTION,
        "history": [],
        "domain": "labour_law",
        "private_scope": None,
    }
    return await service.research(**{**values, **overrides})


@pytest.mark.asyncio
async def test_a_research_searches_each_part_fills_the_gaps_and_follows_citations() -> None:
    service, provider, coordinator = research()
    stages: list[str] = []

    async def record(stage: str) -> None:
        stages.append(stage)

    result = await run(service, on_stage=record)

    # One search per part, doctrine for the question, then the gap the model named; repeats
    # run once.
    assert coordinator.searches == [
        ("geçerli fesih şartları", "primary"),
        ("savunma alınması verim fesih", "primary"),
        ("feshin ispat yükü", "primary"),
        (QUESTION, "doctrine"),
        ("performans ölçütü objektif", "primary"),
    ]
    # Articles 18 and 19 were found; article 20, which the decision rests on, is looked up.
    assert coordinator.article_requests == [[("4857", "20")]]
    assert provider.calls == [
        "gemini-research:ResearchPlan",
        "gemini-research:ResearchGaps",
        "gemini-research:ChatAnswer",
        "gemini-support:SupportReport",
    ]
    # The gap check sees what each part found.
    gaps_prompt = provider.prompts["ResearchGaps"]
    assert "2. Savunma alınması" in gaps_prompt and "savunma alınmalıdır" in gaps_prompt

    report = provider.prompts["ChatAnswer"]
    plan = json.loads(report.rsplit("<research_plan>", 1)[1].split("</research_plan>")[0])
    assert plan == [
        {"alt_soru": "Geçerli fesih şartları", "kaynaklar": [
            "SOURCE_PRIMARY_01", "SOURCE_PRIMARY_02", "SOURCE_PRIMARY_05",
        ]},
        {"alt_soru": "Savunma alınması", "kaynaklar": ["SOURCE_PRIMARY_03", "SOURCE_PRIMARY_04"]},
        {"alt_soru": "İspat yükü", "kaynaklar": ["SOURCE_PRIMARY_02"]},
    ]
    assert report.count(CITING.record.text) == 1 and PROOF.record.text in report
    assert DOCTRINE.record.text in report and "SOURCE_DOCTRINE_*" in report

    content = result.structured_content
    assert content["search_mode"] == "research" and content["web_search_offer"] is None
    assert content["research"] == {
        "parts": [
            {"question": "Geçerli fesih şartları", "sources": 3},
            {"question": "Savunma alınması", "sources": 2},
            {"question": "İspat yükü", "sources": 1},
        ],
        "searches": 5,
        "follow_ups": 1,
        "followed_articles": ["4857 m.20"],
        "passages": 6,
    }
    assert {c["source_id"] for c in result.citations} == {"SOURCE_PRIMARY_03", "SOURCE_PRIMARY_05"}
    assert result.actual_model == "gemini-research"
    assert stages == ["retrieving", "generating", "verifying"]


@pytest.mark.asyncio
async def test_the_parts_and_follow_ups_are_capped() -> None:
    plan = ResearchPlan(
        sub_questions=[
            ResearchQuestion(question=f"Konu {n}", search_query=f"konu {n} fesih")
            for n in range(1, 10)
        ]
    )
    gaps = ResearchGaps(
        follow_ups=[ResearchGap(serves=9, search_query=f"ek arama {n}") for n in range(1, 9)]
    )
    service, _, coordinator = research(FakeProvider(plan, gaps))
    result = await run(service)
    assert len(coordinator.searches) == MAX_SUB_QUESTIONS + 1 + MAX_FOLLOW_UPS
    assert len(result.structured_content["research"]["parts"]) == MAX_SUB_QUESTIONS


@pytest.mark.asyncio
async def test_a_case_file_is_searched_for_every_part() -> None:
    files = FakeFiles()
    service, provider, _ = research(files=files)
    await run(service, private_scope=SCOPE)
    assert files.queries == [
        "geçerli fesih şartları",
        "savunma alınması verim fesih",
        "feshin ispat yükü",
        "performans ölçütü objektif",
    ]
    report = provider.prompts["ChatAnswer"]
    assert "Dosyada savunma alınması verim fesih hakkında bir iddia." in report
    plan = json.loads(report.rsplit("<research_plan>", 1)[1].split("</research_plan>")[0])
    assert "SOURCE_FILE_02" in plan[1]["kaynaklar"]


@pytest.mark.asyncio
async def test_a_research_with_web_on_searches_the_web_once() -> None:
    page = WebHit(
        url="https://hukuk.example.com/performans",
        title="Performans feshi",
        site="hukuk.example.com",
        text="Performans feshinde savunma şarttır.",
        score=0.8,
        retrieved_on="2026-10-02",
        published_date=None,
    )
    web = FakeWebSearch([page])
    service, provider, _ = research(web=web)
    result = await run(service, web=True)
    assert web.queries == ["performans düşüklüğü fesih savunma ispat"]
    assert "web_query: aynı soruyu genel bir web araması" in provider.prompts["ResearchPlan"]
    assert "<web_evidence>" in provider.prompts["ChatAnswer"]
    assert result.structured_content["web_search_status"] == "found"
    # The report wrote no web section, so a note says so rather than leaving it empty.
    assert result.structured_content["web_blocks"]


@pytest.mark.asyncio
async def test_a_research_without_web_never_searches_it() -> None:
    web = FakeWebSearch([])
    service, provider, _ = research(web=web)
    result = await run(service)
    assert web.queries == [] and "<web_evidence>" not in provider.prompts["ChatAnswer"]
    assert "web_query alanını boş bırak" in provider.prompts["ResearchPlan"]
    assert result.structured_content["web_blocks"] == []


@pytest.mark.asyncio
async def test_a_failed_citation_lookup_never_fails_the_research(caplog) -> None:
    service, _, _ = research(coordinator=FakeCoordinator(article_error=RuntimeError("down")))
    result = await run(service)
    assert result.structured_content["research"]["followed_articles"] == []
    assert "Citation following skipped (RuntimeError)" in caplog.text


def test_a_deep_research_cannot_be_an_analysis() -> None:
    from pydantic import ValidationError

    from app.api.chat import ChatRequest

    assert ChatRequest(message="Soru nedir?", deep_research=True, search_mode="web").deep_research
    with pytest.raises(ValidationError):
        ChatRequest(message="Soru nedir?", deep_research=True, search_mode="analysis")
