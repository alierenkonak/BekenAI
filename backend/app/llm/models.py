from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GeneratedClaim(BaseModel):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    text: str = Field(min_length=1, max_length=4000)
    source_ids: list[str] = Field(min_length=1, max_length=10)

    @field_validator("source_ids")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class AnswerSection(BaseModel):
    summary: str = Field(min_length=1, max_length=8000)
    claims: list[GeneratedClaim] = Field(default_factory=list, max_length=30)


class GroundedAnswer(BaseModel):
    answer_status: Literal["answered", "insufficient_evidence"]
    primary_answer: AnswerSection | None = None
    doctrine_answer: AnswerSection | None = None
    limitations: list[str] = Field(default_factory=list, max_length=20)


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
