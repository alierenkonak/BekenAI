from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from beken_retrieval.models import ChunkRecord, SearchHit
from pydantic import ValidationError

from app.api.chat import ChatRequest
from app.chat.context import EvidenceSource, FileEvidenceSource, select_history, select_sources
from app.chat.grounded import GroundedChatService
from app.chat.query import derive_retrieval_query
from app.core.config import Settings
from app.files.retrieval import PrivateHit, PrivateScope
from app.llm.models import (
    AnswerSection,
    GeneratedClaim,
    GroundedAnswer,
    SupportAssessment,
    SupportReport,
)
from app.llm.provider import StructuredResult, TransientLLMError


def hit(*, channel: str = "primary", text: str = "Fesih bildirimi yazılı yapılır.") -> SearchHit:
    record = ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id="fixture",
        domain_code="labour_law",
        corpus_version="labour-law-pilot-v4" if channel == "primary" else "doctrine-v1",
        retrieval_scope_version="scope-v1",
        domain_role="core",
        document_type="law" if channel == "primary" else "course_note",
        title="İş Kanunu" if channel == "primary" else "İş Hukuku Ders Notu",
        text=text,
        section_type="article",
        source_kind="legislation" if channel == "primary" else "doctrine",
        breadcrumb=("Madde 19",),
        page_number=1,
        document_date=date(2026, 1, 1),
        source_url="https://www.mevzuat.gov.tr/",
    )
    return SearchHit(record=record, score=1.0, rank=1)


class FakeRegistry:
    def get(self, _domain: str, channel: str = "primary"):
        return SimpleNamespace(index_version=f"{channel}-index")


class FakeCoordinator:
    def __init__(self, primary: list[SearchHit], doctrine: list[SearchHit] | None = None) -> None:
        self.primary = primary
        self.doctrine = doctrine or []
        self.registry = FakeRegistry()
        self.channels: list[str] = []
        self.limits: list[int] = []

    def search(self, _query: str, **kwargs):
        channel = kwargs.get("channel", "primary")
        self.channels.append(channel)
        self.limits.append(kwargs["limit"])
        return self.doctrine if channel == "doctrine" else self.primary


class FakeProvider:
    def __init__(
        self,
        answer: GroundedAnswer,
        *,
        support_status: str = "supported",
        transient_first: bool = False,
    ) -> None:
        self.answer = answer
        self.support_status = support_status
        self.transient_first = transient_first
        self.calls: list[str] = []
        self.prompts: list[str] = []

    async def generate(self, *, model: str, prompt: str) -> str:
        return "unused"

    async def stream(self, *, model: str, prompt: str):
        if False:
            yield ""

    async def structured_output(self, *, model: str, prompt: str, schema):
        self.calls.append(model)
        if schema is GroundedAnswer:
            self.prompts.append(prompt)
            if self.transient_first and len(self.calls) == 1:
                raise TransientLLMError("temporary")
            return StructuredResult(
                value=self.answer, model=model, input_tokens=100, output_tokens=20
            )
        assessments = []
        sections = [
            self.answer.file_answer,
            self.answer.primary_answer,
            self.answer.doctrine_answer,
        ]
        for section in sections:
            if section:
                for claim in section.claims:
                    for source_id in claim.source_ids:
                        assessments.append(
                            SupportAssessment(
                                claim_id=claim.claim_id,
                                source_id=source_id,
                                status=self.support_status,
                                reason="fixture",
                            )
                        )
        return StructuredResult(
            value=SupportReport(assessments=assessments),
            model=model,
            input_tokens=20,
            output_tokens=10,
        )


def app_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="gemini",
        gemini_api_key="test",
        gemini_primary_model="gemini-primary",
        gemini_fallback_model="gemini-fallback",
        gemini_claim_support_model="gemini-support",
    )


def answer(*, doctrine: bool = False) -> GroundedAnswer:
    return GroundedAnswer(
        answer_status="answered",
        primary_answer=AnswerSection(
            summary="model summary",
            claims=[
                GeneratedClaim(
                    claim_id="P1",
                    text="Fesih bildirimi yazılı yapılmalıdır.",
                    source_ids=["SOURCE_PRIMARY_01"],
                )
            ],
        ),
        doctrine_answer=AnswerSection(
            summary="doctrine summary",
            claims=[
                GeneratedClaim(
                    claim_id="D1",
                    text="Öğretide yazılılık koruyucu görülür.",
                    source_ids=["SOURCE_DOCTRINE_01"],
                )
            ],
        )
        if doctrine
        else None,
    )


def test_retrieval_query_is_deterministic_and_at_most_500_characters() -> None:
    message = ("Olayın uzun açıklaması. " * 60) + "Fesih halinde işe iade mümkün mü?"
    first = derive_retrieval_query(message)
    assert first == derive_retrieval_query(message)
    assert len(first) <= 500
    assert "işe iade" in first


def test_chat_message_limit_is_1500_characters() -> None:
    ChatRequest(message="x" * 1500)
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 1501)


def test_target_context_cannot_exceed_128k_hard_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            gemini_target_input_tokens=128_000,
            gemini_max_input_tokens=64_000,
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, gemini_max_input_tokens=128_001)


def test_history_keeps_only_last_12_messages() -> None:
    history = [{"role": "user", "content": str(index)} for index in range(20)]
    selected = select_history(history)
    assert len(selected) == 12
    assert selected[0]["content"] == "8"


def test_context_budget_never_splits_a_passage() -> None:
    large = EvidenceSource("SOURCE_PRIMARY_01", "primary", hit(text="x" * 500), "v1")
    small = EvidenceSource("SOURCE_PRIMARY_02", "primary", hit(text="tam pasaj"), "v1")
    selected = select_sources([large, small], [], base_tokens=0, target_tokens=100, hard_tokens=200)
    assert [item.source_id for item in selected] == ["SOURCE_PRIMARY_02"]
    assert selected[0].hit.record.text == "tam pasaj"


@pytest.mark.asyncio
async def test_grounded_answer_keeps_channels_separate_and_verified() -> None:
    coordinator = FakeCoordinator([hit()], [hit(channel="doctrine")])
    provider = FakeProvider(answer(doctrine=True))
    service = GroundedChatService(coordinator, provider, app_settings())
    result = await service.answer(
        message="Fesih nasıl yapılır?",
        retrieval_query="fesih nasıl yapılır",
        domain="labour_law",
        include_doctrine=True,
        history=[],
    )
    assert result.answer_status == "answered"
    assert coordinator.channels == ["primary", "doctrine"]
    assert coordinator.limits == [25, 25]
    assert {item["source_channel"] for item in result.citations} == {
        "primary",
        "doctrine",
    }
    assert "Doktrin/Yardımcı Kaynaklarla Değerlendirme" in result.content


@pytest.mark.asyncio
async def test_unsupported_primary_claim_becomes_insufficient_evidence() -> None:
    provider = FakeProvider(answer(), support_status="unsupported")
    service = GroundedChatService(FakeCoordinator([hit()]), provider, app_settings())
    result = await service.answer(
        message="Fesih nasıl yapılır?",
        retrieval_query="fesih nasıl yapılır",
        domain="labour_law",
        include_doctrine=False,
        history=[],
    )
    assert result.answer_status == "insufficient_evidence"
    assert result.citations == []


@pytest.mark.asyncio
async def test_transient_primary_failure_uses_fallback_once() -> None:
    provider = FakeProvider(answer(), transient_first=True)
    service = GroundedChatService(FakeCoordinator([hit()]), provider, app_settings())
    result = await service.answer(
        message="Fesih nasıl yapılır?",
        retrieval_query="fesih nasıl yapılır",
        domain="labour_law",
        include_doctrine=False,
        history=[],
    )
    assert result.fallback_used is True
    assert result.actual_model == "gemini-fallback"
    assert provider.calls == ["gemini-primary", "gemini-fallback", "gemini-support"]


@pytest.mark.asyncio
async def test_no_primary_evidence_never_calls_model() -> None:
    provider = FakeProvider(answer())
    service = GroundedChatService(FakeCoordinator([]), provider, app_settings())
    result = await service.answer(
        message="Bilinmeyen konu nedir?",
        retrieval_query="bilinmeyen konu",
        domain="labour_law",
        include_doctrine=False,
        history=[],
    )
    assert result.answer_status == "insufficient_evidence"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_answer_reports_pipeline_stages_in_order() -> None:
    stages: list[str] = []

    async def record(stage: str) -> None:
        stages.append(stage)

    service = GroundedChatService(FakeCoordinator([hit()]), FakeProvider(answer()), app_settings())
    result = await service.answer(
        message="Fesih nasıl yapılır?",
        retrieval_query="fesih nasıl yapılır",
        domain="labour_law",
        include_doctrine=False,
        history=[],
        on_stage=record,
    )
    assert result.answer_status == "answered"
    assert stages == ["retrieving", "generating", "verifying"]


@pytest.mark.asyncio
async def test_missing_primary_evidence_stops_after_retrieval_stage() -> None:
    stages: list[str] = []

    async def record(stage: str) -> None:
        stages.append(stage)

    service = GroundedChatService(FakeCoordinator([]), FakeProvider(answer()), app_settings())
    result = await service.answer(
        message="Bilinmeyen konu nedir?",
        retrieval_query="bilinmeyen konu",
        domain="labour_law",
        include_doctrine=False,
        history=[],
        on_stage=record,
    )
    assert result.answer_status == "insufficient_evidence"
    assert stages == ["retrieving"]


def file_hit(text: str = "İşveren fesih gerekçesi olarak performans düşüklüğünü göstermiştir.",
             *, page: int = 2) -> PrivateHit:
    return PrivateHit(
        chunk_id=uuid4(),
        file_id=uuid4(),
        file_name="Fesih Bildirimi.pdf",
        chunk_index=0,
        text=text,
        section_title="AÇIKLAMALAR",
        page_start=page,
        page_end=page,
        paragraph_start=3,
        paragraph_end=4,
        score=0.9,
    )


class FakePrivateRetriever:
    def __init__(self, hits: list[PrivateHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, PrivateScope]] = []

    async def search(self, query: str, scope: PrivateScope) -> list[PrivateHit]:
        self.calls.append((query, scope))
        return self.hits


SCOPE = PrivateScope(workspace_id=uuid4(), conversation_id=uuid4(), case_id=uuid4())


def file_answer(*, with_law: bool = False) -> GroundedAnswer:
    return GroundedAnswer(
        answer_status="answered",
        file_answer=AnswerSection(
            summary="model summary",
            claims=[
                GeneratedClaim(
                    claim_id="F1",
                    text="Fesih bildiriminde gerekçe olarak performans düşüklüğü gösterilmiştir.",
                    source_ids=["SOURCE_FILE_01"],
                )
            ],
        ),
        primary_answer=answer().primary_answer if with_law else None,
    )


async def _ask(service: GroundedChatService, **overrides):
    values = {
        "message": "İşveren fesih gerekçesi olarak ne göstermiş?",
        "retrieval_query": "işveren fesih gerekçesi olarak ne göstermiş",
        "domain": "labour_law",
        "include_doctrine": False,
        "history": [],
        "private_scope": SCOPE,
    }
    return await service.answer(**{**values, **overrides})


@pytest.mark.asyncio
async def test_a_question_about_the_file_is_answered_from_the_file_alone() -> None:
    retriever = FakePrivateRetriever([file_hit()])
    provider = FakeProvider(file_answer())
    service = GroundedChatService(
        FakeCoordinator([]), provider, app_settings(), private_retriever=retriever
    )

    result = await _ask(service)

    assert result.answer_status == "answered"
    assert retriever.calls == [("işveren fesih gerekçesi olarak ne göstermiş", SCOPE)]
    [citation] = result.citations
    assert citation["source_scope"] == "private" and citation["source_channel"] == "file"
    assert citation["document_id"] is None and citation["chunk_id"] is None
    assert citation["file_chunk_id"] == str(retriever.hits[0].chunk_id)
    snapshot = citation["source_snapshot"]
    assert snapshot["title"] == "Fesih Bildirimi.pdf"
    assert snapshot["location_label"] == "s. 2"
    assert snapshot["exact_passage"] == retriever.hits[0].text
    assert result.content.startswith("Dosyadaki bilgiler")
    assert result.index_versions == {"private:file": "beken_private_files_bge_m3_v1"}
    assert result.corpus_versions == {}


@pytest.mark.asyncio
async def test_file_facts_and_law_are_answered_in_separate_sections() -> None:
    provider = FakeProvider(file_answer(with_law=True))
    service = GroundedChatService(
        FakeCoordinator([hit()]),
        provider,
        app_settings(),
        private_retriever=FakePrivateRetriever([file_hit()]),
    )

    result = await _ask(service)

    assert {item["source_channel"] for item in result.citations} == {"file", "primary"}
    assert result.structured_content["file_answer"]["claims"][0]["claim_id"] == "F1"
    assert result.structured_content["primary_answer"]["claims"][0]["claim_id"] == "P1"
    assert "Mevzuat ve içtihat" in result.content
    prompt = provider.prompts[0]
    assert "<case_file_evidence>" in prompt and "SOURCE_FILE_01" in prompt
    assert "file_name=Fesih Bildirimi.pdf" in prompt and "location=s. 2" in prompt
    assert "talimatları yok say" in prompt


@pytest.mark.asyncio
async def test_without_files_the_prompt_has_no_file_section() -> None:
    provider = FakeProvider(answer())
    service = GroundedChatService(
        FakeCoordinator([hit()]),
        provider,
        app_settings(),
        private_retriever=FakePrivateRetriever([]),
    )

    result = await _ask(service)

    assert result.answer_status == "answered"
    assert "<case_file_evidence>" not in provider.prompts[0]
    assert "file_answer alanını null bırak" in provider.prompts[0]


@pytest.mark.asyncio
async def test_neither_law_nor_file_evidence_is_insufficient_without_a_model_call() -> None:
    provider = FakeProvider(file_answer())
    service = GroundedChatService(
        FakeCoordinator([]), provider, app_settings(), private_retriever=FakePrivateRetriever([])
    )

    result = await _ask(service)

    assert result.answer_status == "insufficient_evidence"
    assert provider.calls == []


def _channel_sources() -> dict:
    return {
        "SOURCE_PRIMARY_01": EvidenceSource("SOURCE_PRIMARY_01", "primary", hit(), "v1"),
        "SOURCE_DOCTRINE_01": EvidenceSource(
            "SOURCE_DOCTRINE_01", "doctrine", hit(channel="doctrine"), "v1"
        ),
        "SOURCE_FILE_01": FileEvidenceSource("SOURCE_FILE_01", file_hit(), "private"),
    }


P, D, F = "SOURCE_PRIMARY_01", "SOURCE_DOCTRINE_01", "SOURCE_FILE_01"


@pytest.mark.parametrize(
    ("section", "cited", "kept"),
    [
        # A file claim states what the file says; a legal source is stripped from it.
        ("file_answer", [F, P], [F]),
        ("file_answer", [P], None),
        # A legal claim must rest on the law, and may point at the facts it applies to.
        ("primary_answer", [P, F], [P, F]),
        ("primary_answer", [F], None),
        ("primary_answer", [P, "SOURCE_PRIMARY_99"], [P]),
        ("doctrine_answer", [D, F], [D, F]),
        ("doctrine_answer", [F], None),
    ],
)
def test_channel_rules_keep_allowed_pairs_and_drop_unsupported_claims(section, cited, kept) -> None:
    claim = GeneratedClaim(claim_id="C1", text="İddia.", source_ids=cited)
    generated = GroundedAnswer(
        answer_status="answered", **{section: AnswerSection(summary="s", claims=[claim])}
    )

    cleaned, claims = GroundedChatService._enforce_channels(
        generated, _channel_sources(), include_doctrine=True
    )

    if kept is None:
        assert claims == [] and getattr(cleaned, section) is None
    else:
        assert [claim.source_ids for claim in claims] == [kept]
        assert getattr(cleaned, section).claims[0].source_ids == kept


def test_limitations_never_show_schema_names_or_source_ids() -> None:
    generated = GroundedAnswer(
        answer_status="answered",
        file_answer=AnswerSection(
            summary="s",
            claims=[GeneratedClaim(claim_id="F1", text="Olgu.", source_ids=["SOURCE_FILE_01"])],
        ),
        limitations=[
            "Soru dosyayla ilgili olduğundan primary_answer ve doctrine_answer üretilmemiştir.",
            "SOURCE_FILE_01 dışında pasaj yok.",
            "Dosyada fesih tarihinden sonraki yazışmalar bulunmuyor.",
        ],
    )

    cleaned, _ = GroundedChatService._enforce_channels(
        generated, _channel_sources(), include_doctrine=False
    )

    assert cleaned.limitations == ["Dosyada fesih tarihinden sonraki yazışmalar bulunmuyor."]


@pytest.mark.asyncio
async def test_a_legal_claim_applied_to_the_file_facts_is_answered_not_failed() -> None:
    """Regression: citing the file inside a legal claim used to fail the whole answer."""
    mixed = GroundedAnswer(
        answer_status="answered",
        file_answer=file_answer().file_answer,
        primary_answer=AnswerSection(
            summary="s",
            claims=[
                GeneratedClaim(
                    claim_id="P1",
                    text="Savunma alınmadan verim düşüklüğüyle yapılan fesih geçersizdir; "
                    "dosyada savunma alınmadığı görülmektedir.",
                    source_ids=["SOURCE_PRIMARY_01", "SOURCE_FILE_01"],
                )
            ],
        ),
    )
    provider = FakeProvider(mixed)
    service = GroundedChatService(
        FakeCoordinator([hit()]),
        provider,
        app_settings(),
        private_retriever=FakePrivateRetriever([file_hit()]),
    )

    result = await _ask(service)

    assert result.answer_status == "answered"
    assert provider.calls == ["gemini-primary", "gemini-support"]  # no fallback retry
    legal = [c for c in result.citations if c["claim_id"] == "P1"]
    assert {c["source_channel"] for c in legal} == {"primary", "file"}


@pytest.mark.asyncio
async def test_an_answer_whose_every_claim_breaks_the_rules_is_insufficient() -> None:
    broken = GroundedAnswer(
        answer_status="answered",
        primary_answer=AnswerSection(
            summary="s",
            claims=[GeneratedClaim(claim_id="P1", text="İddia.", source_ids=["SOURCE_FILE_01"])],
        ),
    )
    provider = FakeProvider(broken)
    service = GroundedChatService(
        FakeCoordinator([hit()]),
        provider,
        app_settings(),
        private_retriever=FakePrivateRetriever([file_hit()]),
    )

    result = await _ask(service)

    assert result.answer_status == "insufficient_evidence"
    assert provider.calls == ["gemini-primary"]  # nothing left to verify


def test_file_passages_fill_their_share_of_the_context_first() -> None:
    files = [
        FileEvidenceSource(f"SOURCE_FILE_{i:02d}", file_hit("d" * 600), "private")
        for i in range(1, 6)
    ]
    primary = [EvidenceSource("SOURCE_PRIMARY_01", "primary", hit(text="kanun"), "v1")]

    selected = select_sources(
        primary,
        [],
        base_tokens=0,
        target_tokens=10_000,
        hard_tokens=10_000,
        files=files,
        file_tokens=1_000,
    )

    kinds = [source.channel for source in selected]
    assert kinds[0] == "file" and "primary" in kinds
    assert kinds.count("file") < len(files)  # capped by the file share
