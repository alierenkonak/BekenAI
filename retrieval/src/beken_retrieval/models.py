from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    parse_id: str
    document_id: str
    source_document_id: str | None
    domain_code: str
    corpus_version: str
    retrieval_scope_version: str
    domain_role: str
    document_type: str
    title: str
    text: str
    section_type: str
    source_kind: str = "legislation"
    breadcrumb: tuple[str, ...] = ()
    page_number: int | None = None
    authority: str | None = None
    chamber: str | None = None
    case_number: str | None = None
    decision_number: str | None = None
    document_date: date | None = None
    primary_legislation_number: str | None = None
    legislation_numbers: tuple[str, ...] = ()
    article_labels: tuple[str, ...] = ()
    source_url: str | None = None
    author: str | None = None
    publication_year: int | None = None
    citation_text: str | None = None
    retrieval_eligible: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.document_date:
            payload["document_date"] = self.document_date.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChunkRecord:
        values = dict(payload)
        if values.get("document_date") and not isinstance(values["document_date"], date):
            values["document_date"] = date.fromisoformat(str(values["document_date"]))
        for key in ("breadcrumb", "legislation_numbers", "article_labels"):
            values[key] = tuple(values.get(key) or ())
        return cls(**values)


@dataclass(frozen=True)
class SearchFilters:
    document_types: tuple[str, ...] = ()
    authorities: tuple[str, ...] = ()
    chambers: tuple[str, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    legislation_numbers: tuple[str, ...] = ()
    article_labels: tuple[str, ...] = ()
    section_types: tuple[str, ...] = ()
    domain_roles: tuple[str, ...] = ("core", "supplemental")


@dataclass(frozen=True)
class SearchHit:
    record: ChunkRecord
    score: float
    rank: int = 0
    score_breakdown: dict[str, float] = field(default_factory=dict)

    def with_rank(self, rank: int) -> SearchHit:
        return SearchHit(
            record=self.record,
            score=self.score,
            rank=rank,
            score_breakdown=dict(self.score_breakdown),
        )


@dataclass(frozen=True)
class ContextText:
    text: str
    exact_passage: str
    context_builder_version: str
