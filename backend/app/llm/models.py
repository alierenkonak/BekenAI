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


class CaseIssue(BaseModel):
    # A short heading for the report, e.g. "Savunma alınması".
    title: str = Field(min_length=3, max_length=200)
    # How to find the law on it: general legal terms, no names. Clipped in code.
    search_query: str = Field(min_length=3, max_length=2000)


class CaseIssues(BaseModel):
    """The legal issues a case file raises, most decisive first."""

    issues: list[CaseIssue] = Field(min_length=1, max_length=12)


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
