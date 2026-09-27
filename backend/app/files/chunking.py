from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.files.extraction import ExtractedDocument, Paragraph

# BGE-M3's tokenizer spends roughly one token per 3.5 characters of Turkish legal
# prose, so ~1,400 characters is ~400 tokens: long enough to keep an argument
# together, short enough that CPU inference stays fast and page ranges stay tight.
TARGET_CHARS = 1400
MAX_CHARS = 2000
OVERLAP_CHARS = 200
# A section shorter than this ("KONU", a party block) joins the next one instead
# of becoming a chunk that cannot answer anything on its own.
MIN_SECTION_CHARS = 400

_ABBREVIATIONS = frozenset(
    {
        "av", "dr", "prof", "doç", "yrd", "md", "mad", "vd", "vb", "vs", "bkz", "s", "sy",
        "no", "nr", "ltd", "şti", "a.ş", "t.c", "tic", "san", "cad", "sok", "mah", "apt",
        "e", "k", "hmk", "tbk", "ik", "tmk", "hgk", "ygk", "ibk", "ör", "yy", "hd", "cd",
    }
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+(?=[\"“'(]?[A-ZÇĞİÖŞÜ])")


@dataclass(frozen=True)
class FileChunk:
    index: int
    text: str
    section_title: str | None
    page_start: int | None
    page_end: int | None
    paragraph_start: int
    paragraph_end: int
    content_hash: str

    @property
    def location_label(self) -> str:
        if self.page_start is not None:
            if self.page_start == self.page_end:
                return f"s. {self.page_start}"
            return f"s. {self.page_start}–{self.page_end}"
        if self.paragraph_start == self.paragraph_end:
            return f"¶ {self.paragraph_start}"
        return f"¶ {self.paragraph_start}–{self.paragraph_end}"


@dataclass(frozen=True)
class _Unit:
    text: str
    paragraph: int
    page: int | None


def chunk_document(document: ExtractedDocument) -> list[FileChunk]:
    # The heading stays in the chunk text too: "DELİLLER" is often what a question matches.
    sections: list[tuple[str | None, list[_Unit]]] = []
    for paragraph in document.paragraphs:
        if paragraph.heading:
            sections.append((paragraph.text[:300], _units(paragraph)))
            continue
        if not sections:
            sections.append((None, []))
        sections[-1][1].extend(_units(paragraph))

    chunks: list[FileChunk] = []
    buffer: list[_Unit] = []
    buffer_title: str | None = None

    def emit(units: list[_Unit], section: str | None) -> None:
        text = _join(units)
        pages = [unit.page for unit in units if unit.page is not None]
        chunks.append(
            FileChunk(
                index=len(chunks),
                text=text,
                section_title=section,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                paragraph_start=min(unit.paragraph for unit in units),
                paragraph_end=max(unit.paragraph for unit in units),
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
            )
        )

    fresh = 0  # buffered units not yet part of an emitted chunk (the rest is overlap)
    section_emitted = False
    for section_title, units in sections:
        if not fresh:
            buffer = []  # overlap never crosses a section boundary
        elif section_emitted or _length(buffer) >= MIN_SECTION_CHARS:
            emit(buffer, buffer_title)
            buffer, fresh = [], 0
        # Otherwise a whole short section rides along into this one.
        buffer_title = section_title
        section_emitted = False
        for unit in units:
            if buffer and _length(buffer + [unit]) > TARGET_CHARS:
                emit(buffer, buffer_title)
                buffer, fresh = _overlap(buffer, unit), 0
                section_emitted = True
            buffer.append(unit)
            fresh += 1
    if fresh:
        emit(buffer, buffer_title)
    return chunks


def _units(paragraph: Paragraph) -> list[_Unit]:
    if len(paragraph.text) <= MAX_CHARS:
        return [_Unit(paragraph.text, paragraph.ordinal, paragraph.page)]
    units: list[_Unit] = []
    for sentence in _sentences(paragraph.text):
        for piece in _hard_split(sentence):
            units.append(_Unit(piece, paragraph.ordinal, paragraph.page))
    return units


def _sentences(text: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        before = text[start : match.start()]
        last_word = before.rsplit(None, 1)[-1] if before.split() else ""
        token = last_word.rstrip(".!?…").casefold()
        # "Av. Mehmet", "E. 2019/1", initials and ordinals ("9. Hukuk Dairesi",
        # "5. İş Mahkemesi") must not end a sentence.
        if token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha()) or token.isdigit():
            continue
        sentences.append(before.strip())
        start = match.end()
    sentences.append(text[start:].strip())
    return [sentence for sentence in sentences if sentence]


def _hard_split(sentence: str) -> list[str]:
    if len(sentence) <= MAX_CHARS:
        return [sentence]
    pieces: list[str] = []
    current = ""
    for word in sentence.split():
        if current and len(current) + 1 + len(word) > TARGET_CHARS:
            pieces.append(current)
            current = ""
        while len(word) > MAX_CHARS:
            pieces.append(word[:MAX_CHARS])
            word = word[MAX_CHARS:]
        current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    return pieces


def _overlap(previous: list[_Unit], upcoming: _Unit) -> list[_Unit]:
    """Carry the tail of the previous chunk forward so a boundary never splits context."""
    if len(previous) < 2:
        return []
    carried: list[_Unit] = []
    for unit in reversed(previous[1:]):
        if _length([unit, *carried]) > OVERLAP_CHARS:
            break
        carried.insert(0, unit)
    if carried and _length([*carried, upcoming]) > MAX_CHARS:
        return []
    return carried


def _join(units: list[_Unit]) -> str:
    parts: list[str] = []
    for position, unit in enumerate(units):
        if position:
            parts.append(" " if unit.paragraph == units[position - 1].paragraph else "\n")
        parts.append(unit.text)
    return "".join(parts)


def _length(units: list[_Unit]) -> int:
    return len(_join(units))
