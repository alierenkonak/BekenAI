"""Which articles of which laws a Yargıtay decision rests on, read from its text.

Decisions cite the law in many ways: "4857 sayılı İş Kanunu'nun 21 inci maddesinin beşinci
fıkrası", "Türk Borçlar Kanunu'nun ... kenar başlıklı 400 üncü maddesi", "İŞ KANUNU (4857)
Madde 21" or, after the law is named once, "Kanun'un 25 inci maddesi". A reference counts
only when an article number sits right after a law the corpus can name; anything less
certain is left out, because a wrong reference would raise a wrong warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# A law named without its number, and the earliest decision that can mean it: before 7036
# took effect, "İş Mahkemeleri Kanunu" was 5521, which the corpus does not hold.
_NAMED_LAWS: tuple[tuple[str, str, date], ...] = (
    (r"türk borçlar (?:kanunu|yasası)|\btbk\b", "6098", date(2011, 7, 4)),
    (r"(?<!usulü )hukuk muhakemeleri (?:kanunu|yasası)|\bhmk\b", "6100", date(2011, 2, 4)),
    (r"iş mahkemeleri (?:kanunu|yasası)", "7036", date(2017, 10, 25)),
    (r"hukuk uyuşmazlıklarında arabuluculuk (?:kanunu|yasası)", "6325", date(2012, 6, 22)),
    (r"sosyal sigortalar ve genel sağlık sigortası (?:kanunu|yasası)", "5510", date(2006, 6, 16)),
    (r"sendikalar ve toplu iş sözleşmesi (?:kanunu|yasası)", "6356", date(2012, 11, 7)),
    (r"iş sağlığı ve güvenliği (?:kanunu|yasası)", "6331", date(2012, 6, 30)),
    (r"türk medeni (?:kanunu|yasası)|\btmk\b", "4721", date(2002, 1, 1)),
    (r"\biş (?:kanunu|yasası)", "4857", date(2003, 6, 10)),
)
# "Basın İş Kanunu", "Deniz İş Kanunu", "Rusya Federasyonu İş Kanunu": another law whose name
# ends like one of ours.
_FOREIGN_PREFIX = re.compile(
    r"(?:basın|deniz|mahkemeleri|federasyonu|cumhuriyeti|devleti|krallığı|almanya|alman|"
    r"fransa|fransız|ingiltere|rusya|amerika|birleşik)\s+$"
)
_NUMBERED = re.compile(r"(?<![\d/.])(\d{3,4})\s*sayılı")
_PARENTHESISED = re.compile(r"(?:kanunu|yasası)\s*\((\d{4})\)")
# "Kanun'un", "aynı Kanunun", "anılan Yasanın": the law named last.
_ANAPHORA = re.compile(r"(?:kanun|yasa)(?:'?un|'?nın|nun|nın)\b")
_ORDINAL = r"(?:'?\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü|ünci|unci)|\.)?"
_ARTICLE_AFTER = re.compile(
    r"(?<![\d/.])(\d{1,3})(?:\s*/\s*(\d{1,2}))?" + _ORDINAL + r"\s*madde"
)
_ARTICLE_BEFORE = re.compile(r"\b(?:madde|md\.|m\.)\s*(\d{1,3})(?:\s*/\s*(\d{1,2}))?\b")
_LIST = re.compile(
    r"((?:\d{1,3}" + _ORDINAL + r"\s*(?:,|ve|ile)\s*)+\d{1,3})" + _ORDINAL + r"\s*maddeler"
)

_ORDINAL_ONES = [
    "", "birinci", "ikinci", "üçüncü", "dördüncü", "beşinci",
    "altıncı", "yedinci", "sekizinci", "dokuzuncu",
]
PARAGRAPH_WORDS = {word: number for number, word in enumerate(_ORDINAL_ONES) if word}
PARAGRAPH_WORDS["onuncu"] = 10
for _ones in range(1, 10):
    PARAGRAPH_WORDS[f"on {_ORDINAL_ONES[_ones]}"] = 10 + _ones
    PARAGRAPH_WORDS[f"on{_ORDINAL_ONES[_ones]}"] = 10 + _ones
_PARAGRAPH = re.compile(
    r"\s*(?:maddesinin|maddenin)?\s*(?:\(\s*(\d{1,2})\s*\)\s*numaralı\s*|"
    r"(" + "|".join(sorted(PARAGRAPH_WORDS, key=len, reverse=True)) + r")\s*)fıkra"
)
_CHANGED_PARAGRAPH = re.compile(
    r"(?:değişik|iptal|mülga)\s+("
    + "|".join(sorted(PARAGRAPH_WORDS, key=len, reverse=True))
    + r")\s+fıkra"
)
# How close an article number must follow the law that owns it, and how far back
# "Kanun'un" may reach for that law.
_LAW_REACH = 160
_ANAPHORA_REACH = 900


@dataclass(frozen=True)
class ArticleRef:
    law_number: str
    article: str
    # A specific paragraph when the decision names one ("beşinci fıkrası", "20/1").
    paragraph: int | None = None


def fold(text: str) -> str:
    """Lower-case Turkish text without changing its length, so offsets still match."""
    folded = text.replace("İ", "i").replace("I", "ı").replace("’", "'").replace("‘", "'")
    return folded.lower()


def _law_mentions(text: str, decided: date | None) -> list[tuple[int, int, str]]:
    """(start, end, law number) for every law the text names, in order."""
    found: list[tuple[int, int, str]] = []
    for pattern in (_NUMBERED, _PARENTHESISED):
        found += [(m.start(), m.end(), m.group(1)) for m in pattern.finditer(text)]
    numbered = [start for start, _, _ in found]
    for pattern, number, earliest in _NAMED_LAWS:
        if decided is not None and decided < earliest:
            continue
        for match in re.finditer(pattern, text):
            # "4857 sayılı İş Kanunu" is one mention, already counted by its number.
            if any(0 <= match.start() - start <= 60 for start in numbered):
                continue
            if _FOREIGN_PREFIX.search(text[max(0, match.start() - 30) : match.start()]):
                continue
            found.append((match.start(), match.end(), number))
    return sorted(found)


def _paragraph(text: str, end: int, slash: str | None) -> int | None:
    if slash:
        return int(slash)
    match = _PARAGRAPH.match(text, end)
    if match is None:
        return None
    return int(match.group(1)) if match.group(1) else PARAGRAPH_WORDS[match.group(2)]


def article_references(text: str, *, decided: date | None = None) -> list[ArticleRef]:
    """The law articles a decision cites, each once, in a stable order."""
    folded = fold(" ".join(text.split()))
    laws = _law_mentions(folded, decided)
    if not laws:
        return []
    refs: set[ArticleRef] = set()

    def owner(position: int) -> str | None:
        before = [law for law in laws if law[1] <= position]
        if before and position - before[-1][1] <= _LAW_REACH:
            return before[-1][2]
        # "Kanun'un 25 inci maddesi": the law named last, if it was named recently.
        window = folded[max(0, position - 60) : position]
        if before and _ANAPHORA.search(window) and position - before[-1][1] <= _ANAPHORA_REACH:
            return before[-1][2]
        return None

    for match in _LIST.finditer(folded):
        if (law := owner(match.start())) is not None:
            for number in re.findall(r"\d{1,3}", match.group(1)):
                refs.add(ArticleRef(law, number))
    for match in _ARTICLE_AFTER.finditer(folded):
        if (law := owner(match.start())) is not None:
            paragraph = _paragraph(folded, match.end() - len("madde"), match.group(2))
            refs.add(ArticleRef(law, match.group(1), paragraph))
    for match in _ARTICLE_BEFORE.finditer(folded):
        if (law := owner(match.start())) is not None:
            paragraph = int(match.group(2)) if match.group(2) else None
            refs.add(ArticleRef(law, match.group(1), paragraph))
    return sorted(refs, key=lambda ref: (ref.law_number, int(ref.article), ref.paragraph or 0))


def annotation_paragraph(annotation: str) -> int | None:
    """The paragraph an amendment note names: "Değişik birinci fıkra: ..." is 1."""
    match = _CHANGED_PARAGRAPH.search(fold(" ".join(annotation.split())))
    return PARAGRAPH_WORDS[match.group(1)] if match else None
