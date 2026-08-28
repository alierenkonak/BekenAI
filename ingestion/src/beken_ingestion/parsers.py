from __future__ import annotations

import io
import re
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any

from pypdf import PdfReader

from beken_ingestion.chunking import PARSER_VERSION, build_chunks
from beken_ingestion.legal_structure import audit_article_structure, parse_legal_structure
from beken_ingestion.models import DocumentChunk, LegalUnit, ParsedDocument, RawDocument, TextPage
from beken_ingestion.normalization import normalize_legal_text, normalized_identifier, stable_hash


class ExtractionError(ValueError):
    """Raised when a document cannot yield reliable text."""


_ARTICLE_UNIT_TYPES = {
    "article",
    "additional_article",
    "temporary_article",
    "additional_temporary_article",
    "repeated_article",
}
_ARTICLE_LIKE_HEADING = re.compile(
    r"(?im)^\s*(?P<header>(?:EK\s+GEÇİCİ|GEÇİCİ|EK|MÜKERRER)?\s*"
    r"MADDE(?:[ \t]+(?:\d|[-–—])|[ \t]*$)[^\n]*)$"
)


class _VisibleTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _html_text(content: bytes) -> list[TextPage]:
    extractor = _VisibleTextExtractor()
    extractor.feed(content.decode("utf-8", errors="replace"))
    return [TextPage(page_number=None, text="".join(extractor.parts))]


def _pdf_text(content: bytes) -> list[TextPage]:
    try:
        reader = PdfReader(io.BytesIO(content))
        return [
            TextPage(page_number=index, text=page.extract_text() or "")
            for index, page in enumerate(reader.pages, start=1)
        ]
    except Exception as exc:
        raise ExtractionError(f"PDF extraction failed: {type(exc).__name__}") from exc


def _plain_text(content: bytes) -> list[TextPage]:
    return [TextPage(page_number=None, text=content.decode("utf-8", errors="replace"))]


def extract_pages(raw: RawDocument) -> tuple[list[TextPage], str]:
    media_type = raw.media_type.split(";", 1)[0].strip().lower()
    suffix = PurePosixPath(raw.source_url or "").suffix.lower()
    if media_type == "application/pdf" or suffix == ".pdf":
        return _pdf_text(raw.content), "pypdf"
    if media_type in {"text/html", "application/xhtml+xml"} or suffix in {".html", ".htm"}:
        return _html_text(raw.content), "html_parser"
    if media_type.startswith("text/") or suffix in {".txt", ".md"}:
        return _plain_text(raw.content), "plain_text"
    raise ExtractionError(f"Unsupported media type: {raw.media_type}")


def _join_pages(pages: list[TextPage]) -> tuple[str, list[tuple[int, int, int | None]]]:
    output: list[str] = []
    spans: list[tuple[int, int, int | None]] = []
    cursor = 0
    for page in pages:
        normalized = normalize_legal_text(page.text)
        if not normalized:
            continue
        if output:
            output.append("\n\n")
            cursor += 2
        start = cursor
        output.append(normalized)
        cursor += len(normalized)
        spans.append((start, cursor, page.page_number))
    return "".join(output), spans


def _first_match(patterns: tuple[str, ...], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_legal_text(match.group(1))
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    for pattern in (r"^(\d{4})-(\d{2})-(\d{2})$", r"^(\d{2})[./](\d{2})[./](\d{4})$"):
        match = re.match(pattern, text)
        if not match:
            continue
        parts = [int(part) for part in match.groups()]
        year, month, day = parts if len(match.group(1)) == 4 else (parts[2], parts[1], parts[0])
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _court_metadata(text: str, supplied: dict[str, Any]) -> dict[str, Any]:
    chamber = supplied.get("chamber") or _first_match(
        (r"((?:\d+\.?\s*)?Hukuk Dairesi)", r"(Hukuk Genel Kurulu)"), text
    )
    case_number = supplied.get("case_number") or _first_match(
        (r"(?:Esas|E\.)\s*(?:No\.?\s*)?[:：]?\s*([0-9]{4}/[0-9]+)",), text
    )
    decision_number = supplied.get("decision_number") or _first_match(
        (r"(?:Karar|K\.)\s*(?:No\.?\s*)?[:：]?\s*([0-9]{4}/[0-9]+)",), text
    )
    decision_date = supplied.get("document_date") or _first_match(
        (r"(?:Karar Tarihi|Tarih)\s*[:：]?\s*([0-9]{2}[./][0-9]{2}[./][0-9]{4})",),
        text,
    )
    return {
        "authority": supplied.get("authority") or "Yargıtay",
        "chamber": chamber,
        "case_number": case_number,
        "decision_number": decision_number,
        "document_date": _parse_date(decision_date),
    }


def _related_legislation(text: str, supplied: dict[str, Any]) -> tuple[str, ...]:
    values = {str(value).strip() for value in supplied.get("related_legislation", []) if value}
    values.update(re.findall(r"\b([0-9]{4})\s+sayılı", text, flags=re.IGNORECASE))
    return tuple(sorted(values))


def _fingerprint(raw: RawDocument, metadata: dict[str, Any], canonical_hash: str) -> str:
    if metadata["source_kind"] == "court_decision":
        decision_parts = [
            metadata.get("authority"),
            metadata.get("chamber"),
            metadata.get("case_number"),
            metadata.get("decision_number"),
        ]
        if all(decision_parts):
            return "court:" + ":".join(normalized_identifier(str(part)) for part in decision_parts)
    if raw.source_document_id:
        return (
            f"{normalized_identifier(raw.source_name)}:"
            f"{normalized_identifier(raw.source_document_id)}"
        )
    return f"content:{canonical_hash}"


def _validate_legislation_structure(
    text: str,
    legal_units: tuple[LegalUnit, ...],
    chunks: tuple[DocumentChunk, ...],
) -> None:
    supplement_starts = [
        unit.char_start
        for unit in legal_units
        if unit.metadata.get("supplement_type")
    ]
    core_end = min(supplement_starts, default=len(text))
    recognized_article_starts = {
        unit.char_start for unit in legal_units if unit.unit_type in _ARTICLE_UNIT_TYPES
    }
    unrecognized_headings = [
        match.group("header").strip()
        for match in _ARTICLE_LIKE_HEADING.finditer(text, 0, core_end)
        if match.start("header") not in recognized_article_starts
    ]
    if unrecognized_headings:
        raise ExtractionError(
            f"Unrecognized article-like heading(s): {unrecognized_headings[:5]}"
        )

    identities = [
        (unit.unit_type, unit.label)
        for unit in legal_units
        if unit.unit_type in _ARTICLE_UNIT_TYPES and unit.label
    ]
    duplicates = [identity for identity, count in Counter(identities).items() if count > 1]
    if duplicates:
        raise ExtractionError(f"Duplicate article identities: {duplicates[:5]}")

    linked_unit_keys = {key for chunk in chunks for key in chunk.unit_keys}
    unlinked = [unit.unit_key for unit in legal_units if unit.unit_key not in linked_unit_keys]
    if unlinked:
        raise ExtractionError(f"Legal units without a retrieval chunk: {unlinked[:5]}")

    invalid_unit_offsets = [
        unit.unit_key
        for unit in legal_units
        if text[unit.char_start : unit.char_end] != unit.text
    ]
    invalid_chunk_offsets = [
        str(chunk.chunk_index)
        for chunk in chunks
        if text[chunk.char_start : chunk.char_end] != chunk.text
    ]
    if invalid_unit_offsets or invalid_chunk_offsets:
        raise ExtractionError(
            "Exact passage offset validation failed: "
            f"units={invalid_unit_offsets[:5]}, chunks={invalid_chunk_offsets[:5]}"
        )

    covered = bytearray(len(text))
    for chunk in chunks:
        covered[chunk.char_start : chunk.char_end] = b"\x01" * (
            chunk.char_end - chunk.char_start
        )
    uncovered = sum(
        1 for index, character in enumerate(text) if not character.isspace() and not covered[index]
    )
    if uncovered:
        raise ExtractionError(
            f"Retrieval chunks leave {uncovered} non-whitespace characters uncovered"
        )


def parse_document(raw: RawDocument) -> ParsedDocument:
    pages, extraction_method = extract_pages(raw)
    text, page_spans = _join_pages(pages)
    if len(text) < 40:
        raise ExtractionError("Document contains too little extractable text")

    supplied = raw.metadata
    source_kind = str(supplied.get("source_kind", "court_decision"))
    if source_kind not in {"legislation", "court_decision"}:
        raise ExtractionError(f"Unsupported source kind: {source_kind}")

    court = _court_metadata(text, supplied) if source_kind == "court_decision" else {}
    canonical_hash = stable_hash(text)
    has_complete_court_metadata = all(
        court.get(field) for field in ("authority", "chamber", "case_number", "decision_number")
    )
    confidence = 0.95 if source_kind == "legislation" or has_complete_court_metadata else 0.75
    metadata: dict[str, Any] = {
        "source_kind": source_kind,
        "authority": supplied.get("authority") or court.get("authority"),
        "chamber": supplied.get("chamber") or court.get("chamber"),
        "case_number": supplied.get("case_number") or court.get("case_number"),
        "decision_number": supplied.get("decision_number") or court.get("decision_number"),
    }
    title = str(supplied.get("title") or "").strip()
    if not title and source_kind == "court_decision":
        title = " ".join(
            part for part in (metadata.get("chamber"), metadata.get("decision_number")) if part
        )
    title = title or raw.source_document_id or "Başlıksız hukuk belgesi"
    legal_units, provision_events = (
        parse_legal_structure(text, page_spans, extraction_method, confidence)
        if source_kind == "legislation"
        else ((), ())
    )
    parse_metadata: dict[str, Any] = {}
    expectations = supplied.get("domain_metadata", {}).get("article_expectations")
    if source_kind == "legislation" and isinstance(expectations, dict):
        article_audit = audit_article_structure(legal_units, expectations)
        parse_metadata["article_structure_audit"] = article_audit
        if article_audit["status"] != "passed":
            raise ExtractionError(
                "Article structure validation failed: "
                f"missing={article_audit['missing_labels']}, "
                f"duplicates={article_audit['duplicate_explicit_labels']}, "
                f"unexpected={article_audit['unexpected_numeric_labels']}"
            )
    chunks = build_chunks(
        text=text,
        source_kind=source_kind,
        extraction_method=extraction_method,
        confidence=confidence,
        page_spans=page_spans,
        legal_units=legal_units,
        document_title=title,
    )
    if not chunks:
        raise ExtractionError("Document did not produce any chunks")
    if source_kind == "legislation":
        _validate_legislation_structure(text, legal_units, chunks)

    document_date = _parse_date(supplied.get("document_date")) or court.get("document_date")

    return ParsedDocument(
        fingerprint=_fingerprint(raw, metadata, canonical_hash),
        source_name=raw.source_name,
        source_document_id=raw.source_document_id,
        source_kind=source_kind,
        document_type=str(supplied.get("document_type") or source_kind),
        domain=str(supplied.get("domain") or "labour_law"),
        title=title,
        authority=metadata.get("authority"),
        chamber=metadata.get("chamber"),
        case_number=metadata.get("case_number"),
        decision_number=metadata.get("decision_number"),
        document_date=document_date,
        effective_from=_parse_date(supplied.get("effective_from")),
        effective_to=_parse_date(supplied.get("effective_to")),
        canonical_source_url=raw.source_url,
        canonical_content_hash=canonical_hash,
        parser_version=PARSER_VERSION,
        extraction_method=extraction_method,
        extraction_confidence=min(chunk.confidence for chunk in chunks),
        related_legislation=_related_legislation(text, supplied),
        domain_metadata=dict(supplied.get("domain_metadata") or {}),
        parse_metadata=parse_metadata,
        legal_units=legal_units,
        provision_events=provision_events,
        chunks=chunks,
    )
