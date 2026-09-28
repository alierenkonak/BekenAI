from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from beken_retrieval.models import ChunkRecord, SearchHit
from pydantic import ValidationError

from app.api.chat import ChatRequest
from app.chat.context import EvidenceSource, FileEvidenceSource, select_history, select_sources
from app.chat.grounded import ANSWER_FORMAT, GroundedChatService
from app.chat.query import derive_retrieval_query, fallback_plan, plan_query
from app.core.config import Settings
from app.files.retrieval import PrivateHit, PrivateScope
from app.llm.models import (
    AnswerBlock,
    AnswerSentence,
    ChatAnswer,
    QueryPlan,
    SupportAssessment,
    SupportReport,
)
from app.llm.provider import PermanentLLMError, StructuredResult, TransientLLMError
from app.web.search import TransientWebSearchError, WebHit, WebSearchError

P, D, F, W = "SOURCE_PRIMARY_01", "SOURCE_DOCTRINE_01", "SOURCE_FILE_01", "SOURCE_WEB_01"
SCOPE = PrivateScope(workspace_id=uuid4(), conversation_id=uuid4(), case_id=uuid4())
REWRITTEN = "performans düşüklüğü gerekçesiyle savunma alınmadan fesih işe iade tazminat"


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


def file_hit(text: str = "Fesihten önce savunma alınmamıştır.", *, page: int = 2) -> PrivateHit:
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


class FakeRegistry:
    def get(self, _domain: str, channel: str = "primary"):
        return SimpleNamespace(index_version=f"{channel}-index")


class FakeCoordinator:
    def __init__(self, primary: list[SearchHit], doctrine: list[SearchHit] | None = None) -> None:
        self.primary = primary
        self.doctrine = doctrine or []
        self.registry = FakeRegistry()
        self.searches: list[tuple[str, str]] = []

    def search(self, query: str, **kwargs):
        channel = kwargs.get("channel", "primary")
        self.searches.append((query, channel))
        return self.doctrine if channel == "doctrine" else self.primary


class FakePrivateRetriever:
    def __init__(self, hits: list[PrivateHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, PrivateScope]] = []

    async def search(self, query: str, scope: PrivateScope) -> list[PrivateHit]:
        self.calls.append((query, scope))
        return self.hits


class FakeProvider:
    """Plans, answers and verifies from fixtures, recording every call."""

    def __init__(
        self,
        answer: ChatAnswer,
        *,
        plan: QueryPlan | Exception | None = None,
        support: dict[str, str] | None = None,
        skip_support_for: set[tuple[str, str]] | None = None,
        primary_error: Exception | None = None,
    ) -> None:
        self.answer = answer
        self.plan = plan if plan is not None else QueryPlan(intent="legal", search_query=REWRITTEN)
        self.support = support or {}
        self.skip_support_for = skip_support_for or set()
        self.primary_error = primary_error
        self.calls: list[str] = []
        self.prompts: dict[str, str] = {}
        self.options: dict[str, dict] = {}

    async def structured_output(self, *, model: str, prompt: str, schema, **options):
        self.calls.append(f"{model}:{schema.__name__}")
        self.prompts[schema.__name__] = prompt
        self.options[f"{model}:{schema.__name__}"] = options
        if schema is QueryPlan:
            if isinstance(self.plan, Exception):
                raise self.plan
            return StructuredResult(value=self.plan, model=model)
        if schema is ChatAnswer:
            if self.primary_error and model == "gemini-primary":
                raise self.primary_error
            return StructuredResult(value=self.answer, model=model, input_tokens=9, output_tokens=3)
        import json

        pairs = json.loads(prompt[prompt.index("[") :])
        assessments = [
            SupportAssessment(
                claim_id=pair["claim_id"],
                source_id=pair["source_id"],
                status=self.support.get(pair["source_id"], "supported"),
                reason="fixture",
            )
            for pair in pairs
            if (pair["claim_id"], pair["source_id"]) not in self.skip_support_for
        ]
        return StructuredResult(value=SupportReport(assessments=assessments), model=model)


def app_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="gemini",
        gemini_api_key="test",
        gemini_primary_model="gemini-primary",
        gemini_fallback_model="gemini-fallback",
        gemini_claim_support_model="gemini-support",
        gemini_query_model="gemini-query",
    )


def paragraph(*sentences: tuple[str, list[str]]) -> AnswerBlock:
    return AnswerBlock(
        kind="paragraph",
        sentences=[AnswerSentence(text=text, source_ids=ids) for text, ids in sentences],
    )


def chat_answer(*blocks: AnswerBlock, status: str = "answered", limitations=()) -> ChatAnswer:
    return ChatAnswer(answer_status=status, blocks=list(blocks), limitations=list(limitations))


MIXED = chat_answer(
    paragraph(
        ("Evet, bu feshe itiraz edebilirsiniz.", []),
        ("Verim nedeniyle fesihte önce savunma alınmalıdır.", [P]),
        ("Dosyada sizden savunma istenmediği yazıyor.", [F]),
        ("Bu nedenle fesih usulden geçersiz sayılabilir.", [P, F]),
    )
)


def service(
    provider, *, primary=None, doctrine=None, files=None, web=None
) -> GroundedChatService:
    return GroundedChatService(
        FakeCoordinator([hit()] if primary is None else primary, doctrine),
        provider,
        app_settings(),
        private_retriever=FakePrivateRetriever([file_hit()] if files is None else files),
        web_search=web,
    )


async def ask(chat: GroundedChatService, **overrides):
    values = {
        "message": "doğru mu söylemişler, itiraz edemez miyim?",
        "retrieval_query": "doğru mu söylemişler itiraz edemez miyim",
        "domain": "labour_law",
        "include_doctrine": False,
        "history": [
            {"role": "user", "content": "İşveren fesih gerekçesi olarak ne göstermiş?"},
            {"role": "assistant", "content": "Performans düşüklüğü gösterilmiş."},
        ],
        "private_scope": SCOPE,
    }
    return await chat.answer(**{**values, **overrides})


def sentences(result) -> list[dict]:
    return [s for block in result.structured_content["blocks"] for s in block["sentences"]]


def test_retrieval_query_is_deterministic_and_at_most_500_characters() -> None:
    message = ("Olayın uzun açıklaması. " * 60) + "Fesih halinde işe iade mümkün mü?"
    first = derive_retrieval_query(message)
    assert first == derive_retrieval_query(message)
    assert len(first) <= 500
    assert "işe iade" in first


def test_chat_message_limit_is_4000_characters() -> None:
    ChatRequest(message="x" * 4000)
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 4001)


def test_target_context_cannot_exceed_the_hard_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, gemini_target_input_tokens=128_000, gemini_max_input_tokens=64_000)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, gemini_max_input_tokens=192_001)


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


def test_file_passages_fill_their_share_of_the_context_first() -> None:
    files = [
        FileEvidenceSource(f"SOURCE_FILE_{i:02d}", file_hit("d" * 600), "private")
        for i in range(1, 6)
    ]
    primary = [EvidenceSource(P, "primary", hit(text="kanun"), "v1")]
    selected = select_sources(
        primary, [], base_tokens=0, target_tokens=10_000, hard_tokens=10_000,
        files=files, file_tokens=1_000,
    )
    kinds = [source.channel for source in selected]
    assert kinds[0] == "file" and "primary" in kinds
    assert kinds.count("file") < len(files)


@pytest.mark.asyncio
async def test_a_follow_up_is_searched_with_its_conversation_context() -> None:
    """Regression: 'doğru mu söylemişler?' used to be searched as is and matched nothing."""
    provider = FakeProvider(MIXED)
    chat = service(provider, doctrine=[hit(channel="doctrine")])

    result = await ask(chat, include_doctrine=True)

    assert chat.coordinator.searches == [(REWRITTEN, "primary"), (REWRITTEN, "doctrine")]
    assert chat.private_retriever.calls == [(REWRITTEN, SCOPE)]
    assert result.retrieval_query == REWRITTEN
    assert "İşveren fesih gerekçesi" in provider.prompts["QueryPlan"]
    assert provider.calls[0] == "gemini-query:QueryPlan"


@pytest.mark.asyncio
async def test_planner_failure_falls_back_to_the_previous_question() -> None:
    provider = FakeProvider(MIXED, plan=TransientLLMError("provider_temporarily_unavailable"))
    chat = service(provider)

    await ask(chat)

    query = chat.coordinator.searches[0][0]
    assert query.startswith("İşveren fesih gerekçesi") and "itiraz" in query


def test_fallback_plan_without_history_uses_the_message() -> None:
    assert fallback_plan("Kıdem tazminatı nasıl hesaplanır?", []).search_query == (
        "Kıdem tazminatı nasıl hesaplanır?"
    )


def test_fallback_plan_does_not_pair_a_repeated_question_with_itself() -> None:
    question = "Uzaktan çalışana yemek ücreti ödenir mi?"
    history = [{"role": "user", "content": question}, {"role": "assistant", "content": "Yok."}]
    assert fallback_plan(f" {question}", history).search_query == question


@pytest.mark.asyncio
async def test_planner_keeps_legal_queries_short_and_detects_small_talk() -> None:
    long_query = QueryPlan(intent="legal", search_query="fesih " * 200)
    provider = FakeProvider(MIXED, plan=long_query)
    plan = await plan_query(provider, model="m", message="x", history=[])
    assert plan.intent == "legal" and len(plan.search_query) <= 500

    chatty = QueryPlan(intent="conversation", search_query="ignored")
    provider = FakeProvider(MIXED, plan=chatty)
    plan = await plan_query(provider, model="m", message="Merhaba", history=[])
    assert plan == QueryPlan(intent="conversation", search_query="")


@pytest.mark.asyncio
async def test_a_mixed_answer_cites_law_and_file_sentence_by_sentence() -> None:
    provider = FakeProvider(MIXED)
    result = await ask(service(provider))

    assert result.answer_status == "answered"
    assert result.structured_content["format"] == ANSWER_FORMAT
    first, rule, fact, applied = sentences(result)
    assert first["verification"] == "plain" and first["source_ids"] == []
    assert rule["verification"] == "verified" and rule["source_ids"] == [P]
    assert applied["source_ids"] == [P, F]
    by_sentence = {(c["claim_id"], c["source_channel"]) for c in result.citations}
    assert by_sentence == {("S2", "primary"), ("S3", "file"), ("S4", "primary"), ("S4", "file")}
    assert result.content.startswith("Evet, bu feshe itiraz edebilirsiniz.")
    assert result.index_versions == {
        "labour_law:primary": "primary-index",
        "private:file": "beken_private_files_bge_m3_v1",
    }
    prompt = provider.prompts["ChatAnswer"]
    assert "<case_file_evidence>" in prompt and "file_name=Fesih Bildirimi.pdf" in prompt
    assert "Önce soruyu doğrudan cevapla" in prompt


@pytest.mark.asyncio
async def test_a_sentence_whose_sources_fail_verification_stays_marked_unverified() -> None:
    provider = FakeProvider(MIXED, support={F: "unsupported"})
    result = await ask(service(provider))

    fact = sentences(result)[2]
    assert fact["verification"] == "unverified" and fact["source_ids"] == []
    applied = sentences(result)[3]
    assert applied["verification"] == "verified" and applied["source_ids"] == [P]
    assert result.structured_content["unverified_count"] == 1
    assert all(c["source_channel"] != "file" for c in result.citations)


@pytest.mark.asyncio
async def test_a_pair_the_verifier_skipped_is_unverified_not_a_failure() -> None:
    provider = FakeProvider(MIXED, skip_support_for={("S3", F)})
    result = await ask(service(provider))

    assert result.answer_status == "answered"
    assert sentences(result)[2]["verification"] == "unverified"


@pytest.mark.asyncio
async def test_unsourced_specific_facts_are_marked_but_explanation_is_not() -> None:
    answer = chat_answer(
        AnswerBlock(kind="heading", sentences=[AnswerSentence(text="Süreler", source_ids=[P])]),
        paragraph(
            ("Bu konuda acele etmeniz iyi olur.", []),
            ("Arabulucuya 30 gün içinde başvurmalısınız.", []),
        ),
    )
    result = await ask(service(FakeProvider(answer)))

    heading, advice, deadline = sentences(result)
    assert heading["source_ids"] == [] and heading["verification"] == "plain"
    assert advice["verification"] == "plain"
    assert deadline["verification"] == "unverified"


@pytest.mark.asyncio
async def test_unknown_ids_and_leaked_internal_terms_never_reach_the_reader() -> None:
    answer = chat_answer(
        paragraph(("Savunma alınmalıdır [SOURCE_PRIMARY_01].", [P, "SOURCE_PRIMARY_99"])),
        limitations=["primary_answer boş kaldı.", "Dosyada fesih sonrası yazışma yok."],
    )
    result = await ask(service(FakeProvider(answer)))

    [sentence] = sentences(result)
    assert sentence["text"] == "Savunma alınmalıdır."
    assert sentence["source_ids"] == [P]
    assert result.structured_content["limitations"] == ["Dosyada fesih sonrası yazışma yok."]


@pytest.mark.asyncio
async def test_small_talk_is_answered_without_searching_or_verifying() -> None:
    answer = chat_answer(paragraph(("Merhaba! Size iş hukukunda nasıl yardımcı olabilirim?", [])))
    provider = FakeProvider(answer, plan=QueryPlan(intent="conversation"))
    stages: list[str] = []

    async def record(stage: str) -> None:
        stages.append(stage)

    chat = service(provider)
    result = await ask(chat, message="Merhaba", on_stage=record)

    assert chat.coordinator.searches == [] and chat.private_retriever.calls == []
    assert result.answer_status == "answered" and result.citations == []
    assert stages == ["retrieving", "generating"]
    assert "hukuki bir soru değil" in provider.prompts["ChatAnswer"]


@pytest.mark.asyncio
async def test_without_any_source_the_model_explains_that_instead_of_guessing() -> None:
    answer = chat_answer(
        paragraph(("Bu konuda kaynaklarımda bir bilgi bulamadım.", [])),
        status="insufficient_evidence",
    )
    provider = FakeProvider(answer)
    result = await ask(service(provider, primary=[], files=[]))

    assert result.answer_status == "insufficient_evidence"
    assert "ilgili bir pasaj bulunamadı" in provider.prompts["ChatAnswer"]
    assert "gemini-support:SupportReport" not in provider.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        TransientLLMError("provider_temporarily_unavailable"),
        PermanentLLMError("invalid_structured_output"),
        PermanentLLMError("output_truncated"),
    ],
)
async def test_primary_model_failures_fall_back_and_are_logged(error, caplog, monkeypatch) -> None:
    monkeypatch.setattr("app.chat.grounded.PRIMARY_RETRY_DELAY_SECONDS", 0)
    provider = FakeProvider(MIXED, primary_error=error)
    with caplog.at_level(logging.WARNING, logger="bekenai.chat"):
        result = await ask(service(provider))

    assert result.fallback_used and result.actual_model == "gemini-fallback"
    assert f"{type(error).__name__}: {error}" in caplog.text


class FlakyPrimary(FakeProvider):
    """The primary model fails a set number of times before answering."""

    def __init__(self, answer, *, failures: int, error: Exception) -> None:
        super().__init__(answer)
        self.failures = failures
        self.error = error

    async def structured_output(self, *, model: str, prompt: str, schema, **options):
        if schema is ChatAnswer and model == "gemini-primary" and self.failures:
            self.failures -= 1
            self.calls.append(f"{model}:{schema.__name__}")
            raise self.error
        return await super().structured_output(
            model=model, prompt=prompt, schema=schema, **options
        )


def _status_error(status: int) -> TransientLLMError:
    error = TransientLLMError("provider_temporarily_unavailable")
    error.status_code = status
    return error


@pytest.mark.asyncio
async def test_an_overloaded_primary_model_is_retried_once_before_falling_back(
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.chat.grounded.PRIMARY_RETRY_DELAY_SECONDS", 0)
    provider = FlakyPrimary(MIXED, failures=1, error=_status_error(503))
    result = await ask(service(provider))

    assert not result.fallback_used and result.actual_model == "gemini-primary"
    assert provider.calls.count("gemini-primary:ChatAnswer") == 2


@pytest.mark.asyncio
async def test_a_quota_error_falls_back_without_waiting(monkeypatch) -> None:
    monkeypatch.setattr("app.chat.grounded.PRIMARY_RETRY_DELAY_SECONDS", 60)
    provider = FlakyPrimary(MIXED, failures=1, error=_status_error(429))
    result = await ask(service(provider))

    assert result.fallback_used
    assert provider.calls.count("gemini-primary:ChatAnswer") == 1


@pytest.mark.asyncio
async def test_a_request_error_on_the_primary_model_is_not_retried() -> None:
    provider = FakeProvider(MIXED, primary_error=PermanentLLMError("provider_request_failed"))
    with pytest.raises(PermanentLLMError, match="provider_request_failed"):
        await ask(service(provider))


@pytest.mark.asyncio
async def test_answer_reports_pipeline_stages_in_order() -> None:
    stages: list[str] = []

    async def record(stage: str) -> None:
        stages.append(stage)

    await ask(service(FakeProvider(MIXED)), on_stage=record)
    assert stages == ["retrieving", "generating", "verifying"]


@pytest.mark.asyncio
async def test_the_answer_thinks_hard_and_the_verifier_is_deterministic(monkeypatch) -> None:
    monkeypatch.setattr("app.chat.grounded.PRIMARY_RETRY_DELAY_SECONDS", 0)
    provider = FakeProvider(MIXED)
    await ask(service(provider))

    assert provider.options["gemini-primary:ChatAnswer"] == {"thinking_level": "high"}
    assert provider.options["gemini-support:SupportReport"] == {"temperature": 0.0}

    fallback = FakeProvider(MIXED, primary_error=PermanentLLMError("output_truncated"))
    await ask(service(fallback))
    # The fallback model keeps its own defaults; it may not support the thinking setting.
    assert fallback.options["gemini-fallback:ChatAnswer"] == {}


def web_hit(text: str = "Uzaktan çalışana yemek yardımı işyeri uygulamasına bağlıdır.") -> WebHit:
    return WebHit(
        url="https://hukuk.example.com/uzaktan-calisma",
        title="Uzaktan Çalışmada Yan Haklar",
        site="hukuk.example.com",
        text=text,
        score=0.8,
        retrieved_on="2026-09-28",
        published_date="2025-02-01",
    )


class FakeWebSearch:
    index_version = "tavily-advanced"

    def __init__(self, hits: list[WebHit] | None = None, *, error: Exception | None = None):
        self.hits = [web_hit()] if hits is None else hits
        self.error = error
        self.queries: list[str] = []

    async def search(self, query: str) -> list[WebHit]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.hits


WEB_QUERY = "uzaktan çalışan işçi yemek yardımı zorunlu mu Türk iş hukuku"
WEB_PLAN = QueryPlan(intent="legal", search_query=REWRITTEN, web_query=WEB_QUERY)
WEB_ANSWER = ChatAnswer(
    answer_status="answered",
    blocks=[
        paragraph(
            ("Verim nedeniyle fesihte önce savunma alınmalıdır.", [P, W]),
            ("Dosyada sizden savunma istenmediği yazıyor.", [F]),
        )
    ],
    web_blocks=[
        paragraph(
            ("Web'deki bir hukuk sitesi de savunma alınmasını şart görüyor.", [W, P]),
        )
    ],
)


def web_sentences(result) -> list[dict]:
    return [s for block in result.structured_content["web_blocks"] for s in block["sentences"]]


@pytest.mark.asyncio
async def test_web_search_adds_a_labelled_section_after_the_corpus_answer() -> None:
    provider = FakeProvider(WEB_ANSWER, plan=WEB_PLAN)
    web = FakeWebSearch()
    chat = service(provider, web=web)

    result = await ask(chat, search_mode="web")

    # Our usual search runs as always; the web gets only the planner's general query.
    assert chat.coordinator.searches == [(REWRITTEN, "primary")]
    assert chat.private_retriever.calls == [(REWRITTEN, SCOPE)]
    assert web.queries == [WEB_QUERY]
    assert "web_query alanına" in provider.prompts["QueryPlan"]
    prompt = provider.prompts["ChatAnswer"]
    assert "<evidence>" in prompt and "<web_evidence>" in prompt
    assert "Web araması (kullanıcı açtı)" in prompt and "site=hukuk.example.com" in prompt

    # Neither section may borrow the other's sources.
    [rule, fact] = sentences(result)
    [web_claim] = web_sentences(result)
    assert rule["source_ids"] == [P] and fact["source_ids"] == [F]
    assert web_claim["source_ids"] == [W] and web_claim["verification"] == "verified"
    channels = {(c["claim_id"], c["source_channel"], c["source_scope"]) for c in result.citations}
    assert channels == {
        ("S1", "primary", "global"),
        ("S2", "file", "private"),
        ("S3", "web", "web"),
    }
    snapshot = next(c for c in result.citations if c["source_id"] == W)["source_snapshot"]
    assert snapshot["source_url"] == "https://hukuk.example.com/uzaktan-calisma"

    structured = result.structured_content
    assert structured["search_mode"] == "web" and structured["web_search_status"] == "found"
    assert structured["web_search_offered"] is False
    assert "Web araması (resmî kaynak değildir)" in result.content
    assert result.index_versions == {
        "labour_law:primary": "primary-index",
        "private:file": "beken_private_files_bge_m3_v1",
        "web:web": "tavily-advanced",
    }


@pytest.mark.asyncio
async def test_web_sentences_are_verified_like_any_other() -> None:
    provider = FakeProvider(WEB_ANSWER, plan=WEB_PLAN, support={W: "unsupported"})
    result = await ask(service(provider, web=FakeWebSearch()), search_mode="web")

    [web_claim] = web_sentences(result)
    assert web_claim["verification"] == "unverified" and web_claim["source_ids"] == []
    assert all(c["source_channel"] != "web" for c in result.citations)
    assert result.structured_content["unverified_count"] == 1


@pytest.mark.asyncio
async def test_an_empty_web_search_leaves_a_short_note() -> None:
    provider = FakeProvider(MIXED, plan=WEB_PLAN)
    result = await ask(service(provider, web=FakeWebSearch([])), search_mode="web")

    assert "web_blocks alanını boş bırak" in provider.prompts["ChatAnswer"]
    [note] = web_sentences(result)
    assert note["text"] == "Web aramasında bu soruyla ilgili bir sayfa bulunamadı."
    assert note["verification"] == "plain" and note["source_ids"] == []
    # The note gets its own id after the answer's sentences.
    assert note["id"] == f"S{len(sentences(result)) + 1}"
    assert result.structured_content["web_search_status"] == "empty"


@pytest.mark.asyncio
async def test_a_web_section_the_model_left_empty_still_says_so() -> None:
    result = await ask(
        service(FakeProvider(MIXED, plan=WEB_PLAN), web=FakeWebSearch()), search_mode="web"
    )
    [note] = web_sentences(result)
    assert note["text"] == "Web'de bulunan sayfalar bu cevaba ek bir bilgi getirmedi."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("web", "status", "note"),
    [
        (
            FakeWebSearch(error=TransientWebSearchError("web_search_temporarily_unavailable")),
            "web_search_temporarily_unavailable",
            "Web araması şu an yapılamadı",
        ),
        (
            FakeWebSearch(error=WebSearchError("web_search_quota_exceeded")),
            "web_search_quota_exceeded",
            "Bu ayın web araması hakkı dolduğu için",
        ),
        (None, "web_search_unavailable", "Web araması şu an yapılamadı"),
    ],
)
async def test_a_failed_web_search_still_answers_from_our_sources(web, status, note) -> None:
    result = await ask(service(FakeProvider(MIXED, plan=WEB_PLAN), web=web), search_mode="web")

    assert result.answer_status == "answered"
    assert {c["source_channel"] for c in result.citations} == {"primary", "file"}
    assert result.structured_content["web_search_status"] == status
    assert web_sentences(result)[0]["text"].startswith(note)


@pytest.mark.asyncio
async def test_small_talk_with_web_search_on_searches_nothing() -> None:
    answer = chat_answer(paragraph(("Rica ederim!", [])))
    provider = FakeProvider(answer, plan=QueryPlan(intent="conversation"))
    web = FakeWebSearch()
    chat = service(provider, web=web)

    result = await ask(chat, search_mode="web", message="Teşekkürler")

    assert chat.coordinator.searches == [] and web.queries == []
    assert result.structured_content["web_blocks"] == []


@pytest.mark.asyncio
async def test_a_corpus_answer_drops_any_web_section_the_model_wrote() -> None:
    result = await ask(service(FakeProvider(WEB_ANSWER), web=FakeWebSearch()))

    assert result.structured_content["web_blocks"] == []
    assert sentences(result)[0]["source_ids"] == [P]


@pytest.mark.asyncio
async def test_the_web_query_leaves_out_what_only_the_conversation_knows() -> None:
    history = [{"role": "user", "content": "Ahmet Yılmaz'ın fesih bildirimi ne diyor?"}]
    planned = await plan_query(
        FakeProvider(MIXED, plan=WEB_PLAN), model="m", message="x", history=history, for_web=True
    )
    assert planned.web_query == WEB_QUERY and planned.search_query == REWRITTEN

    # A planner that forgot the web query falls back to the user's own words.
    bare = await plan_query(
        FakeProvider(MIXED),
        model="m",
        message="Yemek ücreti zorunlu mu?",
        history=history,
        for_web=True,
    )
    assert bare.web_query == "Yemek ücreti zorunlu mu?"

    fallback = fallback_plan("Yemek ücreti zorunlu mu?", history, for_web=True)
    assert fallback.web_query == "Yemek ücreti zorunlu mu?"
    assert "Ahmet" in fallback.search_query
    assert fallback_plan("Yemek ücreti zorunlu mu?", history).web_query == ""


@pytest.mark.asyncio
async def test_corpus_answers_never_touch_the_web_or_its_planner_rule() -> None:
    provider = FakeProvider(MIXED)
    web = FakeWebSearch()
    await ask(service(provider, web=web))

    assert web.queries == []
    assert "web arama motoruna" not in provider.prompts["QueryPlan"]
    assert "<web_evidence>" not in provider.prompts["ChatAnswer"]


@pytest.mark.asyncio
async def test_web_search_is_offered_only_for_legal_questions_the_corpus_could_not_ground() -> None:
    insufficient = chat_answer(
        paragraph(("Bu konuda kaynaklarımda bir bilgi bulamadım.", [])),
        status="insufficient_evidence",
    )
    result = await ask(service(FakeProvider(insufficient), primary=[], files=[]))
    assert result.structured_content["web_search_offered"] is True

    # Answered, but nothing it cited survived verification.
    result = await ask(service(FakeProvider(MIXED, support={P: "unsupported", F: "unsupported"})))
    assert result.citations == [] and result.structured_content["web_search_offered"] is True

    result = await ask(service(FakeProvider(MIXED)))
    assert result.structured_content["web_search_offered"] is False

    greeting = chat_answer(paragraph(("Merhaba!", [])))
    small_talk = FakeProvider(greeting, plan=QueryPlan(intent="conversation"))
    result = await ask(service(small_talk), message="Merhaba")
    assert result.structured_content["web_search_offered"] is False
