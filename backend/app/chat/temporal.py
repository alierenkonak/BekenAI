"""Yürürlük kontrolü: did a cited provision read the same on the date that matters in the case?

The corpus holds today's text of each law. Its official amendment notes ("(Değişik ikinci
cümle: 7/11/2024-7531/28 md.)") were parsed into legal.provision_events at ingestion, each
tied to the article, paragraph or item it changed. The earlier wording is not stored, so
the check can say that and when a provision changed after the case's date, never what it
said before.

The check itself is code. The model only reports the case's date, and that date is used
only when it appears in the case file or the user's message.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal

from app.chat.decision_refs import ArticleRef, annotation_paragraph

ChangeType = Literal["added", "amended", "repealed", "annulled"]
# changed_after / near_change: a cited provision against the case date. decision_outdated:
# a cited Yargıtay decision rests on an article that changed after it was decided.
CheckLevel = Literal["changed_after", "near_change", "decision_outdated"]

# The date in a note is the amending law's adoption date; it usually takes effect with its
# publication days later, sometimes months later. A case date this soon after it may
# still fall under the old text.
NEAR_CHANGE_DAYS = 183
# The Constitutional Court often postpones an annulment, commonly by nine months.
NEAR_ANNULMENT_DAYS = 366
# Per law passage, in the prompt and the source panel; long articles carry dozens.
MAX_CHANGES_PER_SOURCE = 12
MAX_CHECKS = 8
# A decision resting on many changed articles names the first few in its warning.
MAX_NAMED_PROVISIONS = 3
MAX_ANNOTATION_CHARS = 160
MAX_LABEL_CHARS = 80

_ARTICLE_NAMES = {
    "article": "m.",
    "additional_article": "ek m.",
    "temporary_article": "geçici m.",
    "additional_temporary_article": "ek geçici m.",
    "repeated_article": "mükerrer m.",
}

_MONTHS = {
    "ocak": 1,
    "şubat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "eylül": 9,
    "ekim": 10,
    "kasım": 11,
    "aralık": 12,
}
_NUMERIC_DATE = re.compile(r"(?<![\d.])(\d{1,2})\s?[./-]\s?(\d{1,2})\s?[./-]\s?(\d{4})(?!\d)")
_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_WORD_DATE = re.compile(r"(?<!\d)(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})(?!\d)")


@dataclass(frozen=True)
class ProvisionChange:
    """One official amendment note of a law passage."""

    event_id: str
    event_type: ChangeType
    # What the note changed (unit, paragraph, sentence, phrase…) and the unit it is tied
    # to; in laws without numbered paragraphs an added paragraph is tied to its article.
    target_type: str
    unit_type: str
    change_date: date
    effective_from: date | None
    amending_law: str | None
    provision: str
    annotation: str

    @property
    def whole(self) -> bool:
        """The note added, repealed or annulled the very unit it names, not a part of it."""
        unit = "article" if self.unit_type in _ARTICLE_NAMES else self.unit_type
        return self.target_type in {"unit", unit}

    @property
    def prompt_line(self) -> str:
        where = f"{self.provision}: " if self.provision else ""
        return f"- {where}{self.annotation}"

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "change_date": self.change_date.isoformat(),
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "amending_law": self.amending_law,
            "provision": self.provision,
            "annotation": self.annotation,
        }


@dataclass(frozen=True)
class CaseDate:
    value: date
    label: str


def provision_label(unit_path: Sequence[str]) -> str:
    """'article:3', 'paragraph:12' → 'm.3, 12. fıkra'; books, parts and chapters are left out."""
    parts: list[str] = []
    for element in unit_path:
        kind, _, label = element.partition(":")
        label = label.split("#", 1)[0].strip()
        if not label:
            continue
        if kind in _ARTICLE_NAMES:
            parts.append(f"{_ARTICLE_NAMES[kind]}{label}")
        elif kind == "paragraph":
            parts.append(f"{label}. fıkra")
        elif kind == "item":
            parts.append(f"({label}) bendi")
        elif kind == "subitem":
            parts.append(f"({label}) alt bendi")
    return ", ".join(parts)


def changes_by_chunk(rows: Iterable[Mapping[str, Any]]) -> dict[str, tuple[ProvisionChange, ...]]:
    """Group repository rows by chunk, newest change first, a bounded number per chunk.

    The parser sometimes records one note twice for the same unit; it is listed once.
    """
    grouped: dict[str, list[ProvisionChange]] = {}
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        annotation = " ".join(str(row["raw_annotation"]).split())
        if len(annotation) > MAX_ANNOTATION_CHARS:
            annotation = annotation[: MAX_ANNOTATION_CHARS - 1].rstrip() + "…"
        chunk_id = str(row["chunk_id"])
        provision = provision_label(row["unit_path"] or [])
        if (chunk_id, provision, annotation) in seen:
            continue
        seen.add((chunk_id, provision, annotation))
        grouped.setdefault(chunk_id, []).append(
            ProvisionChange(
                event_id=str(row["event_id"]),
                event_type=row["event_type"],
                target_type=row["target_type"],
                unit_type=row["unit_type"],
                change_date=row["event_date"],
                effective_from=row["effective_from"],
                amending_law=row["source_law_number"],
                provision=provision,
                annotation=annotation,
            )
        )
    return {
        chunk_id: tuple(
            sorted(changes, key=lambda change: change.change_date, reverse=True)[
                :MAX_CHANGES_PER_SOURCE
            ]
        )
        for chunk_id, changes in grouped.items()
    }


def _fold(text: str) -> str:
    # Turkish casing: "ARALIK" is "aralık", "NİSAN" is "nisan".
    return text.replace("İ", "i").replace("I", "ı").lower()


def _valid(year: int, month: int, day: int) -> date | None:
    if not 1900 <= year <= 2100:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def dates_in(text: str) -> list[date]:
    """Every date written as 14.06.2023, 14/06/2023, 2023-06-14 or 14 Haziran 2023."""
    folded = _fold(text)
    found: list[date | None] = []
    found += [_valid(int(y), int(m), int(d)) for d, m, y in _NUMERIC_DATE.findall(folded)]
    found += [_valid(int(y), int(m), int(d)) for y, m, d in _ISO_DATE.findall(folded)]
    found += [_valid(int(y), _MONTHS[m], int(d)) for d, m, y in _WORD_DATE.findall(folded)]
    return [value for value in found if value is not None]


def verified_case_date(raw: str, label: str, *, texts: Iterable[str]) -> CaseDate | None:
    """The model's case date, but only if the file or the message actually states it."""
    written = dates_in(raw[:200])
    if not written:
        return None
    value = written[0]
    if not any(value in dates_in(text) for text in texts):
        return None
    label = " ".join(label.split()).strip(" .:;,")[:MAX_LABEL_CHARS] or "olay tarihi"
    return CaseDate(value=value, label=label)


def assess(change: ProvisionChange, when: date) -> CheckLevel | None:
    if change.effective_from is not None:
        return "changed_after" if when < change.effective_from else None
    if when < change.change_date:
        return "changed_after"
    window = NEAR_ANNULMENT_DAYS if change.event_type == "annulled" else NEAR_CHANGE_DAYS
    return "near_change" if (when - change.change_date).days < window else None


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def check_text(title: str, change: ProvisionChange, level: CheckLevel, case: CaseDate) -> str:
    # The official note in parentheses, as the law text itself prints it.
    head = f"{title} {change.provision} ({change.annotation}):".replace("  ", " ")
    if level == "near_change":
        what = "karar" if change.event_type == "annulled" else "kabul"
        return (
            f"{head} {case.label} ({_day(case.value)}) bu değişiklikten kısa süre sonra. "
            f"Nottaki tarih {what} tarihidir; yürürlük daha sonra başlamış olabilir. Olay "
            "tarihinde hangi metnin geçerli olduğunu kontrol edin."
        )
    if change.whole and change.event_type == "added":
        then = "bu hüküm henüz yoktu"
    elif change.whole and change.event_type in {"repealed", "annulled"}:
        then = "hüküm henüz yürürlükteydi"
    else:
        then = "hükmün metni bugünkünden farklıydı"
    return (
        f"{head} bu değişiklik {case.label} olan {_day(case.value)} tarihinden sonra; "
        f"olay tarihinde {then}."
    )


def temporal_checks(
    sources: Sequence[tuple[str, str, Sequence[ProvisionChange]]],
    dates: Mapping[str, CaseDate],
) -> list[dict[str, Any]]:
    """Compare each cited law passage's changes with the date that matters for it.

    `sources` are (source_id, title, changes) in citation order. A change seen through two
    passages of the same article is reported once; firm warnings come before soft ones.
    """
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_id, title, changes in sources:
        case = dates.get(source_id)
        if case is None:
            continue
        for change in changes:
            level = assess(change, case.value)
            if level is None or change.event_id in seen:
                continue
            seen.add(change.event_id)
            checks.append(
                {
                    "source_id": source_id,
                    "level": level,
                    "title": title,
                    **change.snapshot(),
                    "case_date": case.value.isoformat(),
                    "case_date_label": case.label,
                    "text": check_text(title, change, level, case),
                }
            )
    checks.sort(key=lambda check: check["level"] != "changed_after")
    return checks[:MAX_CHECKS]


# Each targeted search costs Tavily credits; two changed provisions cover almost every answer.
MAX_AMENDMENT_SEARCHES = 2


def changed_after(checks: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The firm warnings of an earlier answer, the ones whose old text a web search may find."""
    return [check for check in checks if check.get("level") == "changed_after"][
        :MAX_AMENDMENT_SEARCHES
    ]


def amendment_query(check: Mapping[str, Any]) -> str:
    """A web query for a provision's text before it changed.

    Built from the corpus's own note (law, provision, amending law); nothing from the user's
    file or message, such as a name or the case date, reaches the search engine this way.
    """
    if check.get("amending_law"):
        changed_by = f"{check['amending_law']} sayılı Kanun"
    elif check.get("event_type") == "annulled":
        changed_by = "Anayasa Mahkemesi iptal kararı"
    else:
        changed_by = ""
    parts = (check.get("title"), check.get("provision"), changed_by, "değişiklik öncesi eski hali")
    return " ".join(" ".join(str(part).split()) for part in parts if part)


def _concerns(paragraph: int | None, row: Mapping[str, Any]) -> bool:
    """Whether a change touches the paragraph a decision cites (any, if it cites none)."""
    if paragraph is None:
        return True
    for element in row["unit_path"] or []:
        kind, _, label = element.partition(":")
        if kind == "paragraph":
            return label.split("#", 1)[0] == str(paragraph)
    if row["target_type"] in {"unit", "article"}:
        return True
    if (named := annotation_paragraph(str(row["raw_annotation"]))) is not None:
        return named == paragraph
    # A paragraph added to the article leaves the cited one as it was.
    return not (row["event_type"] == "added" and row["target_type"] == "paragraph")


def changes_after_decision(
    refs: Sequence[ArticleRef], rows: Iterable[Mapping[str, Any]], decided: date
) -> tuple[ProvisionChange, ...]:
    """Changes made, after a decision, to the articles (and paragraphs) it rests on.

    `rows` are the article changes of `refs`, each with its law_number, article and the
    law's title; a change before the decision is part of the text the court applied.
    """
    cited: dict[tuple[str, str], list[int | None]] = {}
    for ref in refs:
        cited.setdefault((ref.law_number, ref.article), []).append(ref.paragraph)
    changes: dict[str, ProvisionChange] = {}
    for row in rows:
        paragraphs = cited.get((row["law_number"], row["article"]))
        if paragraphs is None or row["event_id"] in changes:
            continue
        took_effect = row["effective_from"] or row["event_date"]
        if took_effect <= decided or not any(_concerns(p, row) for p in paragraphs):
            continue
        [change] = changes_by_chunk([row | {"chunk_id": "decision"}])["decision"]
        changes[str(row["event_id"])] = replace(
            change, provision=f"{row['law_title']} {change.provision}".strip()
        )
    return tuple(
        sorted(changes.values(), key=lambda change: change.change_date, reverse=True)[
            :MAX_CHANGES_PER_SOURCE
        ]
    )


def decision_checks(
    decisions: Sequence[tuple[str, str, date, Sequence[ProvisionChange]]],
    dates: Mapping[str, CaseDate],
) -> list[dict[str, Any]]:
    """Cited decisions given before an article they rest on changed.

    With a case date, only changes in force by then count: a decision on the old text fits
    an event that also happened under it. Without one, the decision is compared with today.
    """
    checks: list[dict[str, Any]] = []
    for source_id, title, decided, changes in decisions:
        case = dates.get(source_id)
        relevant = [
            change
            for change in changes
            if case is None or case.value >= (change.effective_from or change.change_date)
        ]
        if not relevant:
            continue
        latest = relevant[0]
        named = list(dict.fromkeys(change.provision for change in relevant))
        provisions = ", ".join(named[:MAX_NAMED_PROVISIONS]) + (
            f" ve {len(named) - MAX_NAMED_PROVISIONS} hüküm daha"
            if len(named) > MAX_NAMED_PROVISIONS
            else ""
        )
        notes = "; ".join(dict.fromkeys(change.annotation for change in relevant[:2]))
        then = (
            f"{case.label} olan {_day(case.value)} tarihinde ise yeni metin yürürlükteydi."
            if case
            else "bugünkü metinle uyumunu kontrol edin."
        )
        checks.append(
            {
                "source_id": source_id,
                "level": "decision_outdated",
                "title": title,
                **latest.snapshot(),
                "provision": provisions,
                "decision_date": decided.isoformat(),
                "case_date": case.value.isoformat() if case else None,
                "case_date_label": case.label if case else None,
                "text": (
                    f"{title} ({_day(decided)}): dayandığı {provisions} bu karardan sonra "
                    f"değişti ({notes}). Karar maddenin eski haline göre verilmiş; {then}"
                ),
            }
        )
    return checks


_LEVEL_ORDER = {"changed_after": 0, "decision_outdated": 1, "near_change": 2}


def ordered_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Firm warnings first, then outdated decisions, then notes; a bounded number."""
    return sorted(checks, key=lambda check: _LEVEL_ORDER[check["level"]])[:MAX_CHECKS]
