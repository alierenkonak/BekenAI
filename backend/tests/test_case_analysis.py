from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from beken_retrieval.models import ChunkRecord, SearchHit

from app.chat import analysis as analysis_module
from app.chat.analysis import MAX_ISSUES, CaseAnalysisError, CaseAnalysisService
from app.chat.grounded import GroundedChatService
from app.core.config import Settings
from app.files.retrieval import PrivateScope
from app.llm.models import (
    AnswerBlock,
    AnswerSentence,
    CaseDeadline,
    CaseIssue,
    CaseIssues,
    ChatAnswer,
    SupportAssessment,
    SupportReport,
)
from app.llm.provider import StructuredResult, TransientLLMError

SCOPE = PrivateScope(workspace_id=uuid4(), conversation_id=uuid4(), case_id=uuid4())
F1, P1, P2, P3 = "SOURCE_FILE_01", "SOURCE_PRIMARY_01", "SOURCE_PRIMARY_02", "SOURCE_PRIMARY_03"
D1 = "SOURCE_DOCTRINE_01"


def law_hit(text: str, article: str) -> SearchHit:
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
        title="İş Kanunu",
        text=text,
        section_type="article",
        breadcrumb=(article,),
        page_number=1,
        document_date=date(2026, 1, 1),
    )
    return SearchHit(record=record, score=1.0, rank=1)


def chunk_row(text: str, *, file_name: str, index: int, page: int) -> dict:
    return {
        "id": uuid4(),
        "file_id": uuid4(),
        "original_name": file_name,
        "chunk_index": index,
        "text": text,
        "section_title": "AÇIKLAMALAR",
        "page_start": page,
        "page_end": page,
        "paragraph_start": 1,
        "paragraph_end": 2,
    }


ROWS = [
    chunk_row("Davacının iş sözleşmesi performans gerekçesiyle feshedilmiştir.",
              file_name="Dava Dilekçesi.pdf", index=0, page=1),
    chunk_row("Fesihten önce davacının savunması alınmamıştır.",
              file_name="Dava Dilekçesi.pdf", index=1, page=2),
    chunk_row("İşveren, satış rakamları objektif olduğundan savunmaya gerek görmemiştir.",
              file_name="Cevap Dilekçesi.pdf", index=0, page=1),
]
DEFENCE = law_hit("Verimle ilgili fesihte savunma alınmalıdır.", "Madde 19")
GUARANTEE = law_hit("Otuz işçi ve altı ay kıdem iş güvencesi şartıdır.", "Madde 18")
SHARED = law_hit("Fesih bildirimi yazılı yapılır.", "Madde 19")
VIEW = SearchHit(
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
        text="Öğretide savunma alınmadan yapılan verim feshi geçersiz sayılır.",
        section_type="paragraph",
        breadcrumb=(),
        page_number=12,
    ),
    score=1.0,
    rank=1,
)
ISSUES = CaseIssues(
    issues=[
        CaseIssue(title="Savunma alınması", search_query="savunma alınmadan geçerli fesih"),
        CaseIssue(title="İş güvencesi kapsamı", search_query="iş güvencesi şartları kıdem"),
        # The same issue twice is kept once.
        CaseIssue(title="savunma  alınması", search_query="savunma hakkı"),
    ]
)
REPORT = ChatAnswer(
    answer_status="answered",
    blocks=[
        AnswerBlock(
            kind="paragraph",
            sentences=[AnswerSentence(text="Dava, savunma alınmadan yapılan fesihle ilgilidir.")],
        ),
        AnswerBlock(kind="heading", sentences=[AnswerSentence(text="Savunma alınması")]),
        AnswerBlock(
            kind="bullets",
            sentences=[
                AnswerSentence(text="**Kanun ve içtihat:** Savunma alınmalıdır.", source_ids=[P1]),
                AnswerSentence(text="**Öğretide:** Savunmasız verim feshi geçersiz sayılır.",
                               source_ids=[D1]),
                AnswerSentence(text="**Dosyada:** Savunma alınmadığı ileri sürülmüş.",
                               source_ids=[F1]),
            ],
        ),
    ],
)


class FakeCoordinator:
    def __init__(self) -> None:
        self.registry = SimpleNamespace(get=lambda *_: SimpleNamespace(index_version="idx"))
        self.searches: list[tuple[str, str, int]] = []
        self.results = {
            "savunma alınmadan geçerli fesih": [DEFENCE, SHARED],
            "iş güvencesi şartları kıdem": [SHARED, GUARANTEE],
        }
        # Doctrine has a view on the defence only; it is found again for the second issue.
        self.doctrine = {
            "savunma alınmadan geçerli fesih": [VIEW],
            "iş güvencesi şartları kıdem": [VIEW],
        }

    def search(self, query: str, **kwargs):
        channel = kwargs.get("channel", "primary")
        self.searches.append((query, f"{channel}:{kwargs['mode']}", kwargs["limit"]))
        results = self.doctrine if channel == "doctrine" else self.results
        return results.get(query, [])


class FakeProvider:
    def __init__(self, issues: CaseIssues = ISSUES) -> None:
        self.issues = issues
        self.calls: list[str] = []
        self.prompts: dict[str, str] = {}

    async def structured_output(self, *, model: str, prompt: str, schema, **_options):
        self.calls.append(f"{model}:{schema.__name__}")
        self.prompts[schema.__name__] = prompt
        if schema is CaseIssues:
            return StructuredResult(value=self.issues, model=model)
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


class FakeChunks:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.requests: list[tuple[PrivateScope, int]] = []

    async def scope_file_chunks(self, scope: PrivateScope, *, limit: int) -> list[dict]:
        self.requests.append((scope, limit))
        return self.rows[:limit]


def settings() -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key="test",
        gemini_primary_model="gemini-primary",
        gemini_fallback_model="gemini-fallback",
        gemini_claim_support_model="gemini-support",
        gemini_query_model="gemini-query",
        gemini_analysis_model="gemini-analysis",
    )


def analysis(
    provider=None, rows=ROWS, provisions=None
) -> tuple[CaseAnalysisService, FakeProvider, FakeCoordinator]:
    provider = provider or FakeProvider()
    coordinator = FakeCoordinator()
    chat = GroundedChatService(coordinator, provider, settings(), provisions=provisions)
    return CaseAnalysisService(chat, FakeChunks(rows), settings()), provider, coordinator


@pytest.mark.asyncio
async def test_the_analysis_reads_every_file_and_searches_the_law_once_per_issue() -> None:
    service, provider, coordinator = analysis()
    stages: list[str] = []

    async def record(stage: str) -> None:
        stages.append(stage)

    result = await service.analyze(domain="labour_law", private_scope=SCOPE, on_stage=record)

    # Every chunk of every ready file, not the few closest to a question.
    issue_prompt = provider.prompts["CaseIssues"]
    assert all(row["text"] in issue_prompt for row in ROWS)
    report_prompt = provider.prompts["ChatAnswer"]
    assert all(row["text"] in report_prompt for row in ROWS)
    assert "file_name=Cevap Dilekçesi.pdf" in report_prompt

    # One reranked law search per distinct issue, then a doctrine search for each; a passage
    # found twice is cited once.
    assert coordinator.searches == [
        ("savunma alınmadan geçerli fesih", "primary:hybrid_rerank", 8),
        ("iş güvencesi şartları kıdem", "primary:hybrid_rerank", 8),
        ("savunma alınmadan geçerli fesih", "doctrine:hybrid_rerank", 8),
        ("iş güvencesi şartları kıdem", "doctrine:hybrid_rerank", 8),
    ]
    issue_map = json.loads(report_prompt.rsplit("<issues>", 1)[1].split("</issues>")[0])
    assert issue_map == [
        {"konu": "Savunma alınması", "kaynaklar": [P1, P2], "doktrin": [D1]},
        {"konu": "İş güvencesi kapsamı", "kaynaklar": [P2, P3], "doktrin": [D1]},
    ]
    assert report_prompt.count(SHARED.record.text) == 1
    assert report_prompt.count(VIEW.record.text) == 1
    assert "**Öğretide:**" in report_prompt and "SOURCE_DOCTRINE_* doktrindir" in report_prompt

    # The analysis model finds the issues and writes the report; verification is as usual.
    assert provider.calls == [
        "gemini-analysis:CaseIssues",
        "gemini-analysis:ChatAnswer",
        "gemini-support:SupportReport",
    ]
    assert result.actual_model == "gemini-analysis" and not result.fallback_used
    assert stages == ["retrieving", "generating", "verifying"]
    structured = result.structured_content
    assert structured["search_mode"] == "analysis" and structured["web_search_offered"] is False
    assert {(c["source_id"], c["source_channel"]) for c in result.citations} == {
        (P1, "primary"),
        (D1, "doctrine"),
        (F1, "file"),
    }
    assert result.retrieval_query == "Savunma alınması; İş güvencesi kapsamı"


@pytest.mark.asyncio
async def test_without_doctrine_the_report_is_written_from_the_law_and_files() -> None:
    service, provider, coordinator = analysis()
    coordinator.doctrine = {}

    await service.analyze(domain="labour_law", private_scope=SCOPE)

    report_prompt = provider.prompts["ChatAnswer"]
    issue_map = json.loads(report_prompt.rsplit("<issues>", 1)[1].split("</issues>")[0])
    assert all("doktrin" not in issue for issue in issue_map)
    assert "**Öğretide:**" not in report_prompt and "SOURCE_DOCTRINE_*" not in report_prompt


@pytest.mark.asyncio
async def test_a_case_without_ready_files_cannot_be_analysed() -> None:
    service, provider, _ = analysis(rows=[])
    with pytest.raises(CaseAnalysisError, match="case_has_no_ready_files"):
        await service.analyze(domain="labour_law", private_scope=SCOPE)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_the_number_of_issues_is_capped() -> None:
    many = CaseIssues(
        issues=[
            CaseIssue(title=f"Konu {number}", search_query=f"konu {number} fesih")
            for number in range(1, 11)
        ]
    )
    service, _, coordinator = analysis(provider=FakeProvider(many))
    await service.analyze(domain="labour_law", private_scope=SCOPE)
    # A law and a doctrine search for each issue kept.
    assert len(coordinator.searches) == 2 * MAX_ISSUES


@pytest.mark.asyncio
async def test_a_case_too_large_for_one_report_says_what_was_left_out(monkeypatch) -> None:
    monkeypatch.setattr(analysis_module, "ANALYSIS_FILE_TOKENS", 150)
    service, provider, _ = analysis()
    await service.analyze(domain="labour_law", private_scope=SCOPE)

    report_prompt = provider.prompts["ChatAnswer"]
    assert "Dosyaların tamamı analize sığmadı" in report_prompt
    assert ROWS[0]["text"] in report_prompt and ROWS[2]["text"] not in report_prompt


class QuotaExhausted(FakeProvider):
    """The analysis model is out of quota; the fallback model finds the issues."""

    async def structured_output(self, *, model: str, prompt: str, schema, **options):
        if model == "gemini-analysis" and schema is CaseIssues:
            self.calls.append(f"{model}:{schema.__name__}")
            error = TransientLLMError("provider_temporarily_unavailable")
            error.status_code = 429
            raise error
        return await super().structured_output(model=model, prompt=prompt, schema=schema, **options)


@pytest.mark.asyncio
async def test_issue_extraction_falls_back_when_the_analysis_model_is_unavailable() -> None:
    service, provider, _ = analysis(provider=QuotaExhausted())
    await service.analyze(domain="labour_law", private_scope=SCOPE)
    assert provider.calls[:2] == ["gemini-analysis:CaseIssues", "gemini-fallback:CaseIssues"]


class FakeProvisions:
    """Only the defence article changed, after the dismissal in the file."""

    async def provision_changes(self, chunk_ids):
        return [
            {
                "chunk_id": chunk_id,
                "event_id": "defence-change",
                "event_type": "amended",
                "target_type": "unit",
                "unit_type": "article",
                "event_date": date(2023, 11, 8),
                "effective_from": None,
                "source_law_number": "7999",
                "raw_annotation": "Değişik: 8/11/2023-7999/1 md.",
                "unit_path": ["article:19"],
            }
            for chunk_id in chunk_ids
            if chunk_id == DEFENCE.record.chunk_id
        ]


@pytest.mark.asyncio
async def test_each_issue_is_checked_against_the_date_the_file_gives_for_it() -> None:
    dated = CaseIssues(
        issues=[
            CaseIssue(
                title="Savunma alınması",
                search_query="savunma alınmadan geçerli fesih",
                date="14.06.2023",
                date_label="fesih tarihi",
            ),
            # The model made this date up: the file does not contain it.
            CaseIssue(
                title="İş güvencesi kapsamı",
                search_query="iş güvencesi şartları kıdem",
                date="01.01.2020",
                date_label="işe giriş tarihi",
            ),
        ]
    )
    rows = [*ROWS, chunk_row("Fesih bildirimi 14.06.2023 tarihinde tebliğ edilmiştir.",
                             file_name="Fesih Bildirimi.pdf", index=0, page=1)]
    service, provider, _ = analysis(FakeProvider(dated), rows=rows, provisions=FakeProvisions())
    result = await service.analyze(domain="labour_law", private_scope=SCOPE)

    report_prompt = provider.prompts["ChatAnswer"]
    issue_map = json.loads(report_prompt.rsplit("<issues>", 1)[1].split("</issues>")[0])
    assert issue_map[0]["olay_tarihi"] == "fesih tarihi: 14.06.2023"
    assert "olay_tarihi" not in issue_map[1]
    assert "- m.19: Değişik: 8/11/2023-7999/1 md." in report_prompt

    [check] = result.structured_content["temporal_checks"]
    assert (check["source_id"], check["level"], check["case_date_label"]) == (
        P1,
        "changed_after",
        "fesih tarihi",
    )
    # A report is not re-run as a web search.
    assert result.structured_content["web_search_offer"] is None


class OwnDeadlines(FakeProvider):
    """The report model writes its own deadline section, with the comparison wrong."""

    async def structured_output(self, *, model: str, prompt: str, schema, **options):
        result = await super().structured_output(
            model=model, prompt=prompt, schema=schema, **options
        )
        if schema is not ChatAnswer:
            return result
        blocks = [
            *REPORT.blocks,
            AnswerBlock(kind="heading", sentences=[AnswerSentence(text="Kritik süreler")]),
            AnswerBlock(
                kind="bullets",
                sentences=[AnswerSentence(text="Başvuru süresi aşılmıştır.", source_ids=[F1])],
            ),
        ]
        return StructuredResult(value=REPORT.model_copy(update={"blocks": blocks}), model=model)


@pytest.mark.asyncio
async def test_time_limits_are_worked_out_in_code_not_by_the_model() -> None:
    issues = CaseIssues(
        issues=[
            CaseIssue(
                title="Arabuluculuk başvuru süresi",
                search_query="işe iade arabulucu başvuru süresi",
                deadline=CaseDeadline(
                    amount=1,
                    unit="ay",
                    start_label="fesih bildiriminin tebliği",
                    start_date="14.06.2023",
                    act_label="arabulucuya başvuru",
                    act_date="05.07.2023",
                ),
            )
        ]
    )
    rows = [
        chunk_row("Fesih bildirimi 14.06.2023 tarihinde tebliğ edilmiştir.",
                  file_name="Fesih Bildirimi.pdf", index=0, page=1),
        chunk_row("Davacı 05.07.2023 tarihinde arabulucuya başvurmuştur.",
                  file_name="Arabuluculuk Tutanağı.pdf", index=0, page=1),
    ]
    service, provider, coordinator = analysis(OwnDeadlines(issues), rows=rows)
    coordinator.results["işe iade arabulucu başvuru süresi"] = [
        law_hit("Tebliğ tarihinden itibaren bir ay içinde arabulucuya başvurulur.", "Madde 20")
    ]

    result = await service.analyze(domain="labour_law", private_scope=SCOPE)

    # The report model is given the result and told not to work out deadlines itself.
    report_prompt = provider.prompts["ChatAnswer"]
    issue_map = json.loads(report_prompt.rsplit("<issues>", 1)[1].split("</issues>")[0])
    assert issue_map[0]["sure"] == {
        "kural": "1 ay",
        "baslangic": "fesih bildiriminin tebliği: 14.06.2023",
        "son_gun": "yaklaşık 14.07.2023",
        "islem": "arabulucuya başvuru: 05.07.2023",
        "sonuc": "süre içinde",
    }
    assert "Süre hesabı yapma." in report_prompt
    assert "deadline: yalnız konu bir yasal süreye bağlıysa" in provider.prompts["CaseIssues"]

    # Its own deadline section is replaced by the one worked out in code, then verified.
    blocks = result.structured_content["blocks"]
    texts = [sentence["text"] for block in blocks for sentence in block["sentences"]]
    assert "Başvuru süresi aşılmıştır." not in texts
    assert blocks[-2]["sentences"][0]["text"] == "Kritik süreler"
    computed = blocks[-1]["sentences"][0]
    assert computed["text"] == (
        "**Arabuluculuk başvuru süresi:** fesih bildiriminin tebliği (14.06.2023) tarihinden "
        "itibaren 1 ay; son gün yaklaşık 14.07.2023. Arabulucuya başvuru: 05.07.2023, süre "
        "içinde."
    )
    assert computed["source_ids"] == [P1, F1, "SOURCE_FILE_02"]
    assert computed["verification"] == "verified"
