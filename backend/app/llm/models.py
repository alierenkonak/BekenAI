from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QueryPlan(BaseModel):
    """How to search for the latest message, given the conversation so far."""

    intent: Literal["legal", "conversation"]
    # A standalone search query; empty when the message needs no sources. Clipped to
    # the 500-character search limit in code, so a verbose model is not rejected.
    search_query: str = Field(default="", max_length=4000)


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
