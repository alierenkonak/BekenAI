from __future__ import annotations

import io
import re
import statistics
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from xml.etree import ElementTree

from pypdf import PdfReader

PDF = "application/pdf"
TEXT = "text/plain"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_MEDIA_TYPES = (PDF, TEXT, DOCX)

# A technical guard against pathological documents, not a product limit: at the
# measured embedding speed a larger file would occupy the model service for hours.
MAX_PAGES = 1500
MAX_DOCX_XML_BYTES = 64 * 1024 * 1024
# Pages with fewer letters than this carry no usable text layer (scans, stamps).
MIN_PAGE_LETTERS = 20
MAX_EDGE_CHARS = 60

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"))
_PAGE_NUMBER = re.compile(r"^(?:sayfa\s*)?-?\s*\d{1,4}\s*(?:/\s*\d{1,4})?\s*-?$", re.IGNORECASE)
_LIST_ITEM = re.compile(r"^(?:\d{1,3}[.)-]|[a-zçğıöşü][.)]|[-•*–])\s")
_HEADING_STYLE = re.compile(r"^(?:heading|title|baslik|başlık|balk)\s*\d*$", re.IGNORECASE)
# Section titles that Turkish pleadings, defences and judgments reuse. Matched
# against a dotless-i folded, lower-cased line so "AÇIKLAMALAR" and "Açıklamalar" agree.
_KNOWN_HEADING = re.compile(
    r"^(?:[ivx]+[.)-]\s*|\d{1,2}[.)-]\s*|[a-h][.)]\s*)?"
    r"(?:aciklamalar|olaylar|maddi olaylar|hukuki (?:sebepler|nedenler|deliller)|deliller"
    r"|sonuc(?: ve (?:istem|talep))?|talep sonucu|netice-?i talep|konu|ozet|hukum"
    r"|gerekce|karar|ekler|ek listesi|delil listesi|savunmalar?|cevaplarimiz|cevaplar"
    r"|beyanlarimiz|beyanlar|taniklar|tanik beyanlari|bilirkisi raporu|degerlendirme)$"
)
_FOLD = str.maketrans("İIıÇçĞğÖöŞşÜü", "iiiccggoossuu")


class ExtractionError(ValueError):
    """Raised with a stable, user-safe error code as its message."""


@dataclass(frozen=True)
class Paragraph:
    text: str
    ordinal: int
    page: int | None
    heading: bool


@dataclass(frozen=True)
class ExtractedDocument:
    media_type: str
    paragraphs: tuple[Paragraph, ...]
    page_count: int | None
    unreadable_pages: int


def detect_media_type(data: bytes, declared: str) -> str:
    """Confirm the uploaded bytes match the declared type before any parsing."""
    if declared == PDF:
        if b"%PDF-" not in data[:1024]:
            raise ExtractionError("invalid_pdf_signature")
        return PDF
    if declared == TEXT:
        decode_text(data)
        return TEXT
    if declared == DOCX:
        if not data.startswith(b"PK\x03\x04"):
            raise ExtractionError("invalid_docx")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.getinfo("word/document.xml")
        except (zipfile.BadZipFile, KeyError):
            raise ExtractionError("invalid_docx") from None
        return DOCX
    raise ExtractionError("unsupported_media_type")


def decode_text(data: bytes) -> str:
    if b"\x00" in data:
        raise ExtractionError("invalid_text_file")
    # Older Turkish pleadings are often saved by Windows editors as cp1254.
    for encoding in ("utf-8-sig", "cp1254"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        controls = sum(
            1 for char in text if unicodedata.category(char) == "Cc" and char not in "\n\r\t\f"
        )
        if controls > max(8, len(text) // 100):
            raise ExtractionError("invalid_text_file")
        return text
    raise ExtractionError("invalid_text_encoding")


def extract_document(data: bytes, media_type: str) -> ExtractedDocument:
    if media_type == PDF:
        document = _extract_pdf(data)
    elif media_type == TEXT:
        document = _extract_text(data)
    elif media_type == DOCX:
        document = _extract_docx(data)
    else:
        raise ExtractionError("unsupported_media_type")
    if not any(_letters(paragraph.text) for paragraph in document.paragraphs):
        raise ExtractionError("empty_document")
    return document


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value).translate(_INVISIBLE)
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    return re.sub(r"[ \t -  　]+", " ", value)


def is_heading(line: str) -> bool:
    stripped = line.strip().rstrip(":").strip()
    if not 3 <= len(stripped) <= 80 or _letters(stripped) < 3:
        return False
    folded = stripped.translate(_FOLD).lower()
    if _KNOWN_HEADING.match(folded):
        return True
    # "DAVACI : Ahmet Yılmaz" style labels introduce values, not sections.
    if ":" in stripped or stripped.endswith((".", ",", ";")):
        return False
    letters = [char for char in stripped if char.isalpha()]
    return all(char.isupper() for char in letters) and len(stripped.split()) <= 12


def _letters(value: str) -> int:
    return sum(char.isalpha() for char in value)


def _extract_pdf(data: bytes) -> ExtractedDocument:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            # Many court exports only set an owner password; an empty user password opens them.
            try:
                opened = reader.decrypt("")
            except Exception:
                raise ExtractionError("encrypted_pdf") from None
            if not opened:
                raise ExtractionError("encrypted_pdf")
        pages = list(reader.pages)
    except ExtractionError:
        raise
    except Exception:
        raise ExtractionError("unreadable_pdf") from None
    if not pages:
        raise ExtractionError("empty_document")
    if len(pages) > MAX_PAGES:
        raise ExtractionError("too_many_pages")

    raw_pages: list[list[str]] = []
    for page in pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        lines = [line.strip() for line in normalize_text(text).split("\n")]
        raw_pages.append(lines)

    readable = [_letters(" ".join(lines)) >= MIN_PAGE_LETTERS for lines in raw_pages]
    unreadable = readable.count(False)
    if not any(readable) or (len(pages) > 1 and unreadable * 2 > len(pages)):
        raise ExtractionError("scanned_pdf_not_supported")

    repeated = _repeated_edge_lines(raw_pages, readable)
    paragraphs: list[Paragraph] = []
    for page_number, (lines, has_text) in enumerate(zip(raw_pages, readable, strict=True), 1):
        if not has_text:
            continue
        cleaned = _strip_page_edges(lines, repeated)
        for text, heading in _pdf_paragraphs(cleaned):
            paragraphs.append(Paragraph(text, len(paragraphs) + 1, page_number, heading))
    return ExtractedDocument(PDF, tuple(paragraphs), len(pages), unreadable)


def _edge_key(line: str) -> str:
    return re.sub(r"\d+", "#", line.casefold())


def _repeated_edge_lines(pages: list[list[str]], readable: list[bool]) -> set[str]:
    counts: Counter[str] = Counter()
    text_pages = 0
    for lines, has_text in zip(pages, readable, strict=True):
        if not has_text:
            continue
        text_pages += 1
        content = [line for line in lines if line]
        # Running headers and footers are short; a long line is body text even if repeated.
        edges = [line for line in content[:2] + content[-2:] if len(line) <= MAX_EDGE_CHARS]
        counts.update({_edge_key(line) for line in edges})
    if text_pages < 3:
        return set()
    threshold = max(3, (text_pages + 1) // 2)
    return {key for key, count in counts.items() if count >= threshold}


def _strip_page_edges(lines: list[str], repeated: set[str]) -> list[str]:
    """Blank out page numbers and running headers/footers; keep inner blank lines."""
    kept = list(lines)

    def is_noise(line: str) -> bool:
        return bool(_PAGE_NUMBER.match(line)) or _edge_key(line) in repeated

    for _ in range(2):
        first = next((index for index, line in enumerate(kept) if line), None)
        if first is not None and is_noise(kept[first]):
            kept[first] = ""
        last = next((index for index in range(len(kept) - 1, -1, -1) if kept[index]), None)
        if last is not None and is_noise(kept[last]):
            kept[last] = ""
    return kept


def _pdf_paragraphs(lines: list[str]) -> list[tuple[str, bool]]:
    """Rebuild paragraphs from a page's visual lines."""
    lengths = [len(line) for line in lines if line]
    typical = statistics.median(lengths) if lengths else 0
    paragraphs: list[tuple[str, bool]] = []
    current = ""
    previous = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            paragraphs.append((current.strip(), False))
        current = ""

    for line in lines:
        if not line:
            flush()
            previous = ""
            continue
        if is_heading(line):
            flush()
            paragraphs.append((line, True))
            previous = ""
            continue
        starts_new = bool(_LIST_ITEM.match(line)) or (
            previous.endswith((".", ":", ";", "!", "?")) and len(previous) < 0.8 * typical
        )
        if starts_new:
            flush()
        hyphenated = current.endswith("-") and len(current) > 1 and current[-2].isalpha()
        if hyphenated and line[0].islower():
            current = current[:-1] + line
        else:
            current = f"{current} {line}" if current else line
        previous = line
    flush()
    return paragraphs


def _extract_text(data: bytes) -> ExtractedDocument:
    text = normalize_text(decode_text(data))
    raw_pages = text.split("\f")
    paged = len(raw_pages) > 1
    if len(raw_pages) > MAX_PAGES:
        raise ExtractionError("too_many_pages")
    paragraphs: list[Paragraph] = []
    for page_number, page in enumerate(raw_pages, 1):
        blocks = re.split(r"\n\s*\n", page)
        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            buffer: list[str] = []
            for line in lines:
                if is_heading(line):
                    if buffer:
                        paragraphs.append(
                            Paragraph(" ".join(buffer), len(paragraphs) + 1,
                                      page_number if paged else None, False)
                        )
                        buffer = []
                    paragraphs.append(
                        Paragraph(line, len(paragraphs) + 1, page_number if paged else None, True)
                    )
                else:
                    buffer.append(line)
            if buffer:
                paragraphs.append(
                    Paragraph(" ".join(buffer), len(paragraphs) + 1,
                              page_number if paged else None, False)
                )
    return ExtractedDocument(TEXT, tuple(paragraphs), len(raw_pages) if paged else None, 0)


def _extract_docx(data: bytes) -> ExtractedDocument:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise ExtractionError("document_too_large")
            with archive.open(info) as handle:
                # Never trust the declared size: cap the inflated stream itself.
                xml = handle.read(MAX_DOCX_XML_BYTES + 1)
    except ExtractionError:
        raise
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError):
        raise ExtractionError("invalid_docx") from None
    if len(xml) > MAX_DOCX_XML_BYTES:
        raise ExtractionError("document_too_large")
    # WordprocessingML never needs a DTD; refusing one rules out entity expansion.
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ExtractionError("invalid_docx")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise ExtractionError("invalid_docx") from None
    body = root.find(f"{_W}body")
    if body is None:
        raise ExtractionError("invalid_docx")

    paragraphs: list[Paragraph] = []
    for text, styled_heading in _docx_blocks(body):
        text = normalize_text(text).strip()
        text = re.sub(r"\s*\n\s*", " ", text)
        if not text:
            continue
        heading = styled_heading or is_heading(text)
        paragraphs.append(Paragraph(text, len(paragraphs) + 1, None, heading))
    return ExtractedDocument(DOCX, tuple(paragraphs), None, 0)


def _docx_blocks(container: ElementTree.Element):
    for element in container:
        if element.tag == f"{_W}p":
            yield _docx_paragraph_text(element), _docx_is_heading(element)
        elif element.tag == f"{_W}tbl":
            for row in element.iter(f"{_W}tr"):
                cells = []
                for cell in row.findall(f"{_W}tc"):
                    parts = [_docx_paragraph_text(p) for p in cell.iter(f"{_W}p")]
                    cells.append(" ".join(part.strip() for part in parts if part.strip()))
                yield " | ".join(cell for cell in cells if cell), False
        elif element.tag == f"{_W}sdt":
            content = element.find(f"{_W}sdtContent")
            if content is not None:
                yield from _docx_blocks(content)


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{_W}tab":
            parts.append(" ")
        elif node.tag in {f"{_W}br", f"{_W}cr"}:
            parts.append("\n")
    return "".join(parts)


def _docx_is_heading(paragraph: ElementTree.Element) -> bool:
    properties = paragraph.find(f"{_W}pPr")
    if properties is None:
        return False
    if properties.find(f"{_W}outlineLvl") is not None:
        return True
    style = properties.find(f"{_W}pStyle")
    value = style.get(f"{_W}val", "") if style is not None else ""
    return bool(_HEADING_STYLE.match(value))
