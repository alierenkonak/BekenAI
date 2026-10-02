from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QueryPlan(BaseModel):
    """How to search for the latest message, given the conversation so far."""

    intent: Literal["legal", "conversation"]
    # A standalone search query; empty when the message needs no sources. Clipped to
    # the 500-character search limit in code, so a verbose model is not rejected.
    search_query: str = Field(default="", max_length=4000)
    # Only when the user turned web search on: the same question for a public search
    # engine, without names, companies, dates or case details. Clipped like search_query.
    web_query: str = Field(default="", max_length=4000)


class CaseDeadline(BaseModel):
    """The legal time limit an issue turns on, as facts only; code works out the last day."""

    # The limit as the law states it, e.g. 1 and "ay" for applying to mediation.
    amount: int = Field(ge=1, le=3650)
    unit: Literal["gün", "iş günü", "hafta", "ay", "yıl"]
    # The event in the file the limit runs from (e.g. "fesih bildiriminin tebliği") and its
    # date as written there. Checked against the file.
    start_label: str = Field(default="", max_length=300)
    start_date: str = Field(default="", max_length=200)
    # The act that had to be done in time, if the file says it was done, and its date.
    act_label: str = Field(default="", max_length=300)
    act_date: str = Field(default="", max_length=200)


class CaseIssue(BaseModel):
    # A short heading for the report, e.g. "Savunma alınması".
    title: str = Field(min_length=3, max_length=200)
    # How to find the law on it: general legal terms, no names. Clipped in code.
    search_query: str = Field(min_length=3, max_length=2000)
    # The date in the file that decides which text of the law applies (e.g. the date of
    # dismissal), and what it is; empty when the file has none. Checked against the file.
    date: str = Field(default="", max_length=200)
    date_label: str = Field(default="", max_length=300)
    # Only for an issue that turns on a time limit (filing, application, objection).
    deadline: CaseDeadline | None = None


class CaseIssues(BaseModel):
    """The legal issues a case file raises, most decisive first."""

    issues: list[CaseIssue] = Field(min_length=1, max_length=12)


class ResearchQuestion(BaseModel):
    # One part of the question, a short heading for the report, e.g. "Savunma alınması".
    question: str = Field(min_length=3, max_length=300)
    # How to find the law on it: general legal terms, no names. Clipped in code.
    search_query: str = Field(min_length=3, max_length=2000)


class ResearchPlan(BaseModel):
    """The parts of a legal question to research separately, most decisive first."""

    sub_questions: list[ResearchQuestion] = Field(min_length=1, max_length=10)
    # Only when web search is on: the question for a public search engine, without names,
    # companies, dates or case details. Clipped like search_query.
    web_query: str = Field(default="", max_length=4000)


class ResearchGap(BaseModel):
    # The number (from 1) of the part this search serves.
    serves: int = Field(default=1, ge=1, le=10)
    search_query: str = Field(min_length=3, max_length=2000)


class ResearchGaps(BaseModel):
    """Searches for what the first round left uncovered; empty when nothing is missing."""

    follow_ups: list[ResearchGap] = Field(default_factory=list, max_length=10)


class AnswerSentence(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # Sources the sentence rests on; empty for explanation, transitions and guidance.
    source_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("source_ids")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class AnswerBlock(BaseModel):
    kind: Literal["paragraph", "heading", "bullets"]
    sentences: list[AnswerSentence] = Field(min_length=1, max_length=25)


class ChatAnswer(BaseModel):
    """A conversational answer written as blocks of sentences, each citing its sources."""

    answer_status: Literal["answered", "insufficient_evidence"]
    blocks: list[AnswerBlock] = Field(min_length=1, max_length=40)
    # Only when the user turned web search on: what web pages confirm, add to or
    # contradict in the answer above. Cites web pages only; shown after the answer.
    web_blocks: list[AnswerBlock] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=5)
    # The date of the case that decides which text of the law applies, as written in the
    # file or message, and what it is; empty otherwise. Used only if the file states it.
    case_date: str = Field(default="", max_length=200)
    case_date_label: str = Field(default="", max_length=300)
    # Something the answer needed is missing from the sources but could be on the web
    # (a current amount, a recent change, a provision's earlier text).
    web_would_help: bool = False


class SupportAssessment(BaseModel):
    claim_id: str
    source_id: str
    status: Literal["supported", "partial", "unsupported"]
    reason: str = Field(max_length=1000)


class SupportReport(BaseModel):
    assessments: list[SupportAssessment] = Field(default_factory=list, max_length=600)


class ModelMetadata(BaseModel):
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ProviderResult(BaseModel):
    value: dict
    metadata: ModelMetadata
