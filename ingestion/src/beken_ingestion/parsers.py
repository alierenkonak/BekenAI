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
    r"M[ \t]*ADDE(?:[ \t]*(?:\d|[lIıİ](?:\d|\b)|[-–—])|[ \t]*$)[^\n]*)$"
)
_COURT_NUMBER = r"[0-9]{4}/(?:\([0-9]+\))?[0-9]+(?:-[0-9]+)?"
_COURT_EXPORT_CREATED = re.compile(
    r"(?im)^.*?kullanıcısı tarafından\s+\d{4}-\d{2}-\d{2}\s+"
    r"\d{2}:\d{2}:\d{2}\s+tarihinde oluşturuldu\.\s*$"
)
_COURT_EXPORT_ANONYMIZATION = re.compile(
    r"(?ims)^Yargıtay İçtihat Merkezinde yayımlanan kararlardaki kişisel veriler\s+"
    r"[\"“]Yargıtay İçtihat Merkezi Kararlarındaki Kişisel Verilerin Anonim\s+"
    r"Hale Getirilmesine Dair Yönerge[\"”]\s+uyarınca anonimleştirilmiştir\.\s*$"
)
_COURT_EXPORT_PAGE_COUNTER = re.compile(r"(?m)^\s*\d+\s*/\s*\d+\s*$")


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


def _clean_court_export_page(text: str) -> tuple[str, bool]:
    cleaned = _COURT_EXPORT_CREATED.sub("", text)
    cleaned = _COURT_EXPORT_ANONYMIZATION.sub("", cleaned)
    cleaned = _COURT_EXPORT_PAGE_COUNTER.sub("", cleaned)
    return cleaned, cleaned != text


def _join_pages(
    pages: list[TextPage], *, clean_court_export: bool = False
) -> tuple[str, list[tuple[int, int, int | None]], int]:
    output: list[str] = []
    spans: list[tuple[int, int, int | None]] = []
    cursor = 0
    cleaned_page_count = 0
    for page in pages:
        page_text = page.text
        if clean_court_export:
            page_text, changed = _clean_court_export_page(page_text)
            cleaned_page_count += int(changed)
        normalized = normalize_legal_text(page_text)
        if not normalized:
            continue
        if output:
            output.append("\n\n")
            cursor += 2
        start = cursor
        output.append(normalized)
        cursor += len(normalized)
        spans.append((start, cursor, page.page_number))
    return "".join(output), spans, cleaned_page_count


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


def _court_header(text: str) -> str:
    decision_marker = re.search(r"(?im)^\s*KARAR\s*$", text)
    start = decision_marker.end() if decision_marker else 0
    return text[start : start + 6_000]


def _court_chamber(header: str) -> str | None:
    for line in header.splitlines():
        identifier = normalized_identifier(line).replace("-", "")
        chamber_match = re.fullmatch(r"(?P<number>\d{1,2})hukukdairesi", identifier)
        if chamber_match:
            return f"{int(chamber_match.group('number'))}. Hukuk Dairesi"
        if identifier == "hukukgenelkurulu":
            return "Hukuk Genel Kurulu"
    return None


def _court_metadata(text: str, supplied: dict[str, Any]) -> dict[str, Any]:
    header = _court_header(text)
    chamber = _court_chamber(header) or _first_match(
        (r"((?:\d+\.?\s*)?Hukuk Dairesi)", r"(Hukuk Genel Kurulu)"), header
    )
    case_number = _first_match(
        (rf"(?:Esas|E\.)\s*(?:No\.?\s*)?[:：]?\s*({_COURT_NUMBER})",), header
    )
    decision_number = _first_match(
        (rf"(?:Karar|K\.)\s*(?:No\.?\s*)?[:：]?\s*({_COURT_NUMBER})",), header
    )
    outcome_dates = re.findall(
        r"(?is)(\d{1,2}[./]\d{1,2}[./]\d{4})\s*"
        r"(?:tarihinde|gününde)"
        r"(?:(?!\d{1,2}[./]\d{1,2}[./]\d{4}).){0,260}?"
        r"\bkarar\s+verildi\b",
        text,
    )
    decision_date = outcome_dates[-1] if outcome_dates else _first_match(
        (
            r"(?:Karar Tarihi|Tarih)\s*[:：]?\s*"
            r"([0-9]{1,2}[./][0-9]{1,2}[./][0-9]{4})",
        ),
        header,
    )
    return {
        "authority": supplied.get("authority") or "Yargıtay",
        "chamber": chamber or supplied.get("chamber"),
        "case_number": case_number or supplied.get("case_number"),
        "decision_number": decision_number or supplied.get("decision_number"),
        "document_date": _parse_date(decision_date) or _parse_date(
            supplied.get("document_date")
        ),
        "extracted_chamber": chamber,
        "extracted_case_number": case_number,
        "extracted_decision_number": decision_number,
    }


def _normalized_court_value(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _validate_court_metadata(court: dict[str, Any], supplied: dict[str, Any]) -> None:
    comparisons = {
        "chamber": court.get("extracted_chamber"),
        "case_number": court.get("extracted_case_number"),
        "decision_number": court.get("extracted_decision_number"),
    }
    for field, extracted in comparisons.items():
        expected = supplied.get(field)
        if expected and extracted and _normalized_court_value(expected) != _normalized_court_value(
            extracted
        ):
            raise ExtractionError(
                "Court metadata mismatch for "
                f"{field}: expected={expected!r}, extracted={extracted!r}"
            )
    requirements = supplied.get("domain_metadata", {}).get("court_metadata_requirements")
    if requirements == "complete":
        missing = [
            field
            for field in ("chamber", "case_number", "decision_number", "document_date")
            if not court.get(field)
        ]
        if missing:
            raise ExtractionError(f"Incomplete court metadata: {missing}")


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
    expectations: dict[str, Any] | None = None,
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
        and match.group("header").casefold().count("madde") == 1
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
    allowed_duplicates = {
        str(value)
        for value in (expectations or {}).get("allowed_duplicate_labels", [])
    }
    duplicates = [
        identity
        for identity, count in Counter(identities).items()
        if count > 1 and f"{identity[0]}:{identity[1]}" not in allowed_duplicates
    ]
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
    supplied = raw.metadata
    source_kind = str(supplied.get("source_kind", "court_decision"))
    if source_kind not in {"legislation", "court_decision"}:
        raise ExtractionError(f"Unsupported source kind: {source_kind}")
    pages, extraction_method = extract_pages(raw)
    text, page_spans, cleaned_page_count = _join_pages(
        pages,
        clean_court_export=source_kind == "court_decision",
    )
    if len(text) < 40:
        raise ExtractionError("Document contains too little extractable text")

    court = _court_metadata(text, supplied) if source_kind == "court_decision" else {}
    if source_kind == "court_decision":
        _validate_court_metadata(court, supplied)
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
        authority = str(metadata.get("authority") or "").strip()
        chamber = str(metadata.get("chamber") or "").strip()
        heading = (
            chamber
            if authority and chamber.casefold().startswith(authority.casefold())
            else " ".join(part for part in (authority, chamber) if part)
        )
        references = [
            f"E. {metadata['case_number']}" if metadata.get("case_number") else "",
            f"K. {metadata['decision_number']}" if metadata.get("decision_number") else "",
        ]
        title = ", ".join(part for part in (heading, *references) if part)
    title = title or raw.source_document_id or "Başlıksız hukuk belgesi"
    legal_units, provision_events = (
        parse_legal_structure(text, page_spans, extraction_method, confidence)
        if source_kind == "legislation"
        else ((), ())
    )
    parse_metadata: dict[str, Any] = {}
    if cleaned_page_count:
        parse_metadata["text_cleanup"] = {
            "method": "yargitay_export_footer_v1",
            "cleaned_page_count": cleaned_page_count,
            "raw_artifact_modified": False,
        }
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
        _validate_legislation_structure(text, legal_units, chunks, expectations)

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
