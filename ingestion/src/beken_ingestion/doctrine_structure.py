from __future__ import annotations

import re
from dataclasses import dataclass

from beken_ingestion.models import LegalUnit, TextPage
from beken_ingestion.normalization import normalize_legal_text, normalized_identifier, stable_hash

_HEADER_PATTERNS = (
    re.compile(r"^\s*(?:\d+|[IVXLCDM]+)\s*\|\s*RAGIP\s+KARAKUŞ\s*$", re.IGNORECASE),
    re.compile(r"^\s*İŞ\s+HUKUKU\s*\|\s*(?:\d+|[IVXLCDM]+)\s*$", re.IGNORECASE),
)
_LINE_BREAK_HYPHEN = re.compile(
    r"(?<=[A-Za-zÇĞİÖŞÜçğıöşü])-[ \t]*\n[ \t]*(?=[a-zçğıöşü])"
)
_CHAPTER = re.compile(
    r"^(?P<label>BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|ALTINCI|"
    r"YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU)\s+BÖLÜM$"
)
_TOPIC = re.compile(r"^§\s*(?P<label>\d+)?\s*\.?\s*(?P<title>.+)$")
_ROMAN = re.compile(r"^(?P<label>[IVXLCDM]+)\.\s+(?P<title>.+)$")
_LETTER = re.compile(r"^(?P<label>[A-ZÇĞİÖŞÜ])\.\s+(?P<title>.+)$")
_SUBITEM = re.compile(r"^(?P<label>[a-zçğıöşü])\)\s+(?P<title>.+)$")
_BIBLIOGRAPHY = re.compile(r"(?m)^\s*YARARLANILAN KAYNAKLAR\s*$")
_NONEMPTY_LINE = re.compile(r"(?m)^\s*(?P<line>[^\n]+?)\s*$")


@dataclass(frozen=True)
class _Heading:
    start: int
    level: int
    unit_type: str
    label: str | None
    heading: str


def clean_doctrine_pages(pages: list[TextPage]) -> tuple[list[TextPage], int]:
    """Remove layout-only headers and repair PDF line-wrap hyphenation."""
    cleaned_pages: list[TextPage] = []
    changed_pages = 0
    for page in pages:
        original = page.text
        repaired = _LINE_BREAK_HYPHEN.sub("", original)
        lines = [
            line
            for line in repaired.splitlines()
            if not any(pattern.fullmatch(line) for pattern in _HEADER_PATTERNS)
        ]
        cleaned = "\n".join(lines)
        changed_pages += int(cleaned != original)
        cleaned_pages.append(TextPage(page_number=page.page_number, text=cleaned))
    return cleaned_pages, changed_pages


def _page_for_offset(
    page_spans: list[tuple[int, int, int | None]], offset: int
) -> int | None:
    for start, end, page_number in page_spans:
        if start <= offset < end:
            return page_number
    return None


def _offset_for_page(
    page_spans: list[tuple[int, int, int | None]], page_number: int
) -> int | None:
    if page_number == 1 and page_spans and all(
        candidate is None for _, _, candidate in page_spans
    ):
        return page_spans[0][0]
    for start, _, candidate in page_spans:
        if candidate is not None and candidate >= page_number:
            return start
    return None


def _heading_lines(text: str, body_start: int, body_end: int) -> list[_Heading]:
    lines = list(_NONEMPTY_LINE.finditer(text, body_start, body_end))
    headings: list[_Heading] = []
    for index, match in enumerate(lines):
        line = normalize_legal_text(match.group("line"))
        chapter = _CHAPTER.fullmatch(line)
        if chapter:
            title = ""
            for following in lines[index + 1 : index + 4]:
                candidate = normalize_legal_text(following.group("line"))
                if candidate and candidate.upper() == candidate and not _TOPIC.fullmatch(candidate):
                    title = candidate
                    break
            heading = " — ".join(value for value in (line, title) if value)
            headings.append(_Heading(match.start(), 1, "chapter", chapter.group("label"), heading))
            continue
        topic = _TOPIC.fullmatch(line)
        if topic:
            headings.append(
                _Heading(match.start(), 2, "section", topic.group("label"), topic.group("title"))
            )
            continue
        roman = _ROMAN.fullmatch(line)
        if roman and roman.group("title").upper() == roman.group("title"):
            headings.append(
                _Heading(match.start(), 3, "part", roman.group("label"), roman.group("title"))
            )
            continue
        letter = _LETTER.fullmatch(line)
        if letter:
            headings.append(
                _Heading(
                    match.start(),
                    4,
                    "paragraph",
                    letter.group("label"),
                    letter.group("title"),
                )
            )
            continue
        subitem = _SUBITEM.fullmatch(line)
        if subitem:
            headings.append(
                _Heading(match.start(), 5, "item", subitem.group("label"), subitem.group("title"))
            )
    return headings


def parse_doctrine_structure(
    text: str,
    page_spans: list[tuple[int, int, int | None]],
    extraction_method: str,
    confidence: float,
    *,
    content_page_start: int,
) -> tuple[tuple[LegalUnit, ...], dict[str, int]]:
    body_start = _offset_for_page(page_spans, content_page_start)
    if body_start is None:
        raise ValueError(f"Doctrine content page {content_page_start} is not present")
    bibliography_match = _BIBLIOGRAPHY.search(text, body_start)
    bibliography_start = bibliography_match.start() if bibliography_match else len(text)
    headings = _heading_lines(text, body_start, bibliography_start)
    if not headings:
        raise ValueError("Doctrine structure contains no recognized headings")

    units: list[LegalUnit] = []
    if body_start:
        front_text = text[:body_start].rstrip()
        if front_text:
            units.append(
                LegalUnit(
                    unit_index=0,
                    unit_key="doctrine:front-matter",
                    parent_key=None,
                    unit_path=("doctrine:front-matter",),
                    unit_type="metadata",
                    label="front_matter",
                    heading="Ön Bölüm",
                    text=front_text,
                    page_number=_page_for_offset(page_spans, 0),
                    char_start=0,
                    char_end=len(front_text),
                    content_hash=stable_hash(front_text),
                    extraction_method=extraction_method,
                    confidence=confidence,
                    metadata={"retrieval_eligible": False, "breadcrumb_label": "Ön Bölüm"},
                )
            )

    stack: list[tuple[int, str, tuple[str, ...]]] = []
    occurrences: dict[str, int] = {}
    for position, heading in enumerate(headings):
        while stack and stack[-1][0] >= heading.level:
            stack.pop()
        base = normalized_identifier(f"{heading.unit_type}-{heading.label or heading.heading}")
        occurrences[base] = occurrences.get(base, 0) + 1
        unit_key = f"doctrine:{base}:{occurrences[base]}"
        parent_key = stack[-1][1] if stack else None
        parent_path = stack[-1][2] if stack else ()
        unit_path = (*parent_path, unit_key)
        next_boundary = bibliography_start
        for candidate in headings[position + 1 :]:
            if candidate.level <= heading.level:
                next_boundary = candidate.start
                break
        passage = text[heading.start:next_boundary].rstrip()
        units.append(
            LegalUnit(
                unit_index=len(units),
                unit_key=unit_key,
                parent_key=parent_key,
                unit_path=unit_path,
                unit_type=heading.unit_type,
                label=heading.label,
                heading=heading.heading,
                text=passage,
                page_number=_page_for_offset(page_spans, heading.start),
                char_start=heading.start,
                char_end=heading.start + len(passage),
                content_hash=stable_hash(passage),
                extraction_method=extraction_method,
                confidence=confidence,
                metadata={
                    "retrieval_eligible": True,
                    "heading_level": heading.level,
                    "breadcrumb_label": heading.heading,
                },
            )
        )
        stack.append((heading.level, unit_key, unit_path))

    if bibliography_start < len(text):
        bibliography_text = text[bibliography_start:].rstrip()
        units.append(
            LegalUnit(
                unit_index=len(units),
                unit_key="doctrine:bibliography",
                parent_key=None,
                unit_path=("doctrine:bibliography",),
                unit_type="metadata",
                label="bibliography",
                heading="Yararlanılan Kaynaklar",
                text=bibliography_text,
                page_number=_page_for_offset(page_spans, bibliography_start),
                char_start=bibliography_start,
                char_end=bibliography_start + len(bibliography_text),
                content_hash=stable_hash(bibliography_text),
                extraction_method=extraction_method,
                confidence=confidence,
                metadata={
                    "retrieval_eligible": False,
                    "breadcrumb_label": "Yararlanılan Kaynaklar",
                },
            )
        )

    return tuple(units), {
        "recognized_heading_count": len(headings),
        "front_matter_page_count": max(content_page_start - 1, 0),
        "bibliography_detected": int(bibliography_match is not None),
    }
