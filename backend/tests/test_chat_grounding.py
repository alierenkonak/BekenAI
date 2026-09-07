from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from beken_retrieval.models import ChunkRecord, SearchHit
from pydantic import ValidationError

from app.api.chat import ChatRequest
from app.chat.context import EvidenceSource, select_history, select_sources
from app.chat.grounded import GroundedChatService
from app.chat.query import derive_retrieval_query
from app.core.config import Settings
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

    async def generate(self, *, model: str, prompt: str) -> str:
        return "unused"

    async def stream(self, *, model: str, prompt: str):
        if False:
            yield ""

    async def structured_output(self, *, model: str, prompt: str, schema):
        self.calls.append(model)
        if schema is GroundedAnswer:
            if self.transient_first and len(self.calls) == 1:
                raise TransientLLMError("temporary")
            return StructuredResult(
                value=self.answer, model=model, input_tokens=100, output_tokens=20
            )
        assessments = []
        sections = [self.answer.primary_answer, self.answer.doctrine_answer]
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
