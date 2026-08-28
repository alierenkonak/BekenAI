from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RawDocument:
    source_name: str
    source_document_id: str | None
    source_url: str | None
    media_type: str
    content: bytes
    retrieved_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextPage:
    page_number: int | None
    text: str


@dataclass(frozen=True)
class DocumentChunk:
    chunk_index: int
    section_type: str
    text: str
    page_number: int | None
    char_start: int
    char_end: int
    content_hash: str
    extraction_method: str
    confidence: float
    unit_keys: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LegalUnit:
    unit_index: int
    unit_key: str
    parent_key: str | None
    unit_path: tuple[str, ...]
    unit_type: str
    label: str | None
    heading: str | None
    text: str
    page_number: int | None
    char_start: int
    char_end: int
    content_hash: str
    extraction_method: str
    confidence: float
    review_status: str = "accepted"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvisionEvent:
    event_index: int
    legal_unit_key: str | None
    event_type: str
    target_type: str
    raw_annotation: str
    authority: str | None = None
    source_law_number: str | None = None
    source_law_article: str | None = None
    case_number: str | None = None
    decision_number: str | None = None
    event_date: date | None = None
    official_gazette_date: date | None = None
    official_gazette_number: str | None = None
    effective_from: date | None = None
    target_char_start: int | None = None
    target_char_end: int | None = None
    confidence: float = 0.7
    review_status: str = "needs_review"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    fingerprint: str
    source_name: str
    source_document_id: str | None
    source_kind: str
    document_type: str
    domain: str
    title: str
    authority: str | None
    chamber: str | None
    case_number: str | None
    decision_number: str | None
    document_date: date | None
    effective_from: date | None
    effective_to: date | None
    canonical_source_url: str | None
    canonical_content_hash: str
    parser_version: str
    extraction_method: str
    extraction_confidence: float
    related_legislation: tuple[str, ...]
    domain_metadata: dict[str, Any]
    parse_metadata: dict[str, Any]
    legal_units: tuple[LegalUnit, ...]
    provision_events: tuple[ProvisionEvent, ...]
    chunks: tuple[DocumentChunk, ...]


@dataclass(frozen=True)
class IngestionOutcome:
    document_id: str
    artifact_id: str | None
    parse_id: str | None
    duplicate_document: bool
    duplicate_artifact: bool
    chunk_count: int
