from __future__ import annotations

import re
from dataclasses import dataclass

from beken_ingestion.models import DocumentChunk, LegalUnit
from beken_ingestion.normalization import stable_hash

PARSER_VERSION = "2026.08.3"

_DECISION_SECTION = re.compile(
    r"(?im)^(?P<header>İDDİA|DAVACI(?:NIN)? İSTEMİ|SAVUNMA|DAVALI(?:NIN)? CEVABI|"
    r"GEREKÇE|HUKUKİ DEĞERLENDİRME|SONUÇ|HÜKÜM)\s*:?[ \t]*$"
)
_PRIMARY_LEGISLATION_TYPES = {
    "metadata",
    "book",
    "part",
    "chapter",
    "section",
    "article",
    "additional_article",
    "temporary_article",
    "additional_temporary_article",
    "repeated_article",
    "annex",
}
_TYPE_LABELS = {
    "book": "Kitap",
    "part": "Kısım",
    "chapter": "Bölüm",
    "section": "Ayırım",
    "article": "Madde",
    "additional_article": "Ek Madde",
    "temporary_article": "Geçici Madde",
    "additional_temporary_article": "Ek Geçici Madde",
    "repeated_article": "Mükerrer Madde",
    "paragraph": "Fıkra",
    "item": "Bent",
    "subitem": "Alt Bent",
    "sentence": "Cümle",
    "annex": "Ek",
}


@dataclass(frozen=True)
class Section:
    kind: str
    start: int
    end: int
    label: str | None = None


def _structured_sections(text: str, source_kind: str) -> list[Section]:
    if source_kind == "legislation":
        return []
    matches = list(_DECISION_SECTION.finditer(text))
    if not matches:
        return []
    sections: list[Section] = []
    if matches[0].start() > 0:
        sections.append(Section("metadata", 0, matches[0].start()))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = match.group("header")
        kind = label.casefold().replace(" ", "_")
        sections.append(Section(kind, match.start(), end, label))
    return sections


def _fallback_sections(text: str) -> list[Section]:
    sections: list[Section] = []
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, re.DOTALL):
        sections.append(Section("paragraph", match.start(), match.end()))
    return sections or ([Section("full_text", 0, len(text))] if text else [])


def _split_oversized(
    text: str,
    section: Section,
    max_chars: int,
    preferred_boundaries: tuple[int, ...] = (),
) -> list[Section]:
    if section.end - section.start <= max_chars:
        return [section]
    result: list[Section] = []
    cursor = section.start
    while cursor < section.end:
        proposed_end = min(cursor + max_chars, section.end)
        if proposed_end < section.end:
            structural = [value for value in preferred_boundaries if cursor < value <= proposed_end]
            boundary = structural[-1] if structural else text.rfind("\n", cursor, proposed_end)
            if boundary <= cursor:
                boundary = text.rfind(". ", cursor, proposed_end)
                boundary = boundary + 1 if boundary > cursor else proposed_end
            proposed_end = boundary
        result.append(Section(section.kind, cursor, proposed_end, section.label))
        cursor = proposed_end
        while cursor < section.end and text[cursor].isspace():
            cursor += 1
    return result


def _page_for_offset(page_spans: list[tuple[int, int, int | None]], offset: int) -> int | None:
    for start, end, page_number in page_spans:
        if start <= offset < end:
            return page_number
    return None


def _overlapping_units(
    units: tuple[LegalUnit, ...], start: int, end: int
) -> tuple[LegalUnit, ...]:
    return tuple(unit for unit in units if unit.char_start < end and unit.char_end > start)


def _breadcrumb(
    document_title: str | None,
    unit: LegalUnit | None,
    units: tuple[LegalUnit, ...],
) -> list[str]:
    result = [document_title] if document_title else []
    if not unit:
        return result
    units_by_key = {candidate.unit_key: candidate for candidate in units}
    chain: list[LegalUnit] = []
    current: LegalUnit | None = unit
    while current:
        chain.append(current)
        current = units_by_key.get(current.parent_key) if current.parent_key else None
    for ancestor in reversed(chain):
        if ancestor.unit_type == "metadata":
            continue
        if ancestor.unit_type in {"book", "part", "chapter", "section"} and ancestor.heading:
            value = ancestor.heading
        else:
            display = _TYPE_LABELS.get(ancestor.unit_type)
            value = f"{display} {ancestor.label}" if display and ancestor.label else None
        if value and value not in result:
            result.append(value)
    return result


def build_chunks(
    text: str,
    source_kind: str,
    extraction_method: str,
    confidence: float,
    page_spans: list[tuple[int, int, int | None]],
    *,
    legal_units: tuple[LegalUnit, ...] = (),
    document_title: str | None = None,
    max_chars: int = 3_000,
) -> tuple[DocumentChunk, ...]:
    if source_kind == "legislation" and legal_units:
        sections = [
            Section(unit.unit_type, unit.char_start, unit.char_end, unit.label)
            for unit in legal_units
            if unit.unit_type in _PRIMARY_LEGISLATION_TYPES
        ]
    else:
        sections = _structured_sections(text, source_kind) or _fallback_sections(text)
    child_boundaries = tuple(
        sorted(
            unit.char_start
            for unit in legal_units
            if unit.unit_type in {"paragraph", "item", "subitem", "sentence"}
        )
    )
    split_sections = [
        piece
        for section in sections
        for piece in _split_oversized(text, section, max_chars, child_boundaries)
    ]
    chunks: list[DocumentChunk] = []
    for section in split_sections:
        passage = text[section.start : section.end].strip()
        if not passage:
            continue
        section_text = text[section.start : section.end]
        leading = len(section_text) - len(section_text.lstrip())
        start = section.start + leading
        end = start + len(passage)
        overlapping = _overlapping_units(legal_units, start, end)
        most_specific = min(
            overlapping,
            key=lambda unit: unit.char_end - unit.char_start,
            default=None,
        )
        metadata: dict[str, object] = {}
        if section.label:
            metadata["label"] = section.label
        breadcrumb = _breadcrumb(document_title, most_specific, legal_units)
        if breadcrumb:
            metadata["breadcrumb"] = breadcrumb
        if most_specific and most_specific.unit_type == "annex":
            metadata["table_parse_status"] = "unparsed"
        chunks.append(
            DocumentChunk(
                chunk_index=len(chunks),
                section_type=most_specific.unit_type if most_specific else section.kind,
                text=passage,
                page_number=_page_for_offset(page_spans, start),
                char_start=start,
                char_end=end,
                content_hash=stable_hash(passage),
                extraction_method=extraction_method,
                confidence=confidence,
                unit_keys=tuple(unit.unit_key for unit in overlapping),
                metadata=metadata,
            )
        )
    return tuple(chunks)
