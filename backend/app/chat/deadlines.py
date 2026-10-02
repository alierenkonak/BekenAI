"""Legal time limits in a case analysis, worked out in code rather than by the model.

The model that reads the case file names, for an issue that turns on a time limit, the
limit (e.g. 1 ay), the event it runs from and the act that had to be done in time, with
their dates. Code checks the dates against the file and the limit against the law found
for the issue, then works out the last day and whether the act came in time. A report
once said an application made on 05.07.2023 missed a limit that ended on 14.07.2023.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.chat.context import EvidenceSource, FileEvidenceSource
from app.chat.decision_refs import fold
from app.chat.temporal import CaseDate, dates_in, verified_case_date
from app.llm.models import AnswerBlock, AnswerSentence, CaseDeadline, ChatAnswer

DEADLINES_HEADING = "Kritik süreler"
APPROXIMATE_NOTE = (
    "Son günler resmî tatiller hesaba katılmadan hesaplandı; kesin son gün ayrıca kontrol "
    "edilmelidir."
)
# Sources cited for each fact of a deadline: the limit, its start, the act.
SOURCES_PER_FACT = 2

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
# The unit with the endings it takes in a law text: "bir aylık", "iki hafta içinde".
_UNITS = {
    "gün": r"gün(?:lük|ü|e|de|den|dür)?",
    "iş günü": r"iş\s+gün(?:ü|lük)",
    "hafta": r"hafta(?:lık|sı|ya|da|dan|dır)?",
    "ay": r"ay(?:lık|ı|a|da|dan|dır)?",
    "yıl": r"yıl(?:lık|ı|a|da|dan|dır)?",
}


def _number_words(amount: int) -> str:
    """15 → "on\\s*beş", the way a law writes a number, joined or spaced."""
    hundreds, rest = divmod(amount % 1000, 100)
    tens, ones = divmod(rest, 10)
    parts: list[str] = []
    if hundreds:
        parts += ["yüz"] if hundreds == 1 else [_ONES[hundreds], "yüz"]
    if tens:
        parts.append(_TENS[tens])
    if ones:
        parts.append(_ONES[ones])
    return r"\s*".join(parts)


def period_pattern(amount: int, unit: str) -> re.Pattern[str]:
    """The limit as a law text writes it, in digits or words: "1 ay", "bir aylık"."""
    number = rf"(?:{amount}|{_number_words(amount)})"
    return re.compile(rf"(?<!\w){number}\s+{_UNITS[unit]}(?!\w)")


def last_day(start: date, amount: int, unit: str) -> date:
    """The last day of a limit, as HMK m.92 counts it.

    The start day is not counted; a limit in weeks, months or years ends on the matching
    day of the last one, or on the month's last day when that month is shorter. Working
    days skip Saturdays and Sundays only; official holidays (HMK m.93) are not known here.
    """
    if unit == "gün":
        return start + timedelta(days=amount)
    if unit == "hafta":
        return start + timedelta(weeks=amount)
    if unit == "iş günü":
        day, left = start, amount
        while left:
            day += timedelta(days=1)
            if day.weekday() < 5:
                left -= 1
        return day
    months = amount * 12 if unit == "yıl" else amount
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


@dataclass(frozen=True)
class Deadline:
    issue: str
    period: str
    start: CaseDate
    last: date
    act: CaseDate | None
    source_ids: tuple[str, ...]

    @property
    def in_time(self) -> bool | None:
        return None if self.act is None else self.act.value <= self.last

    @property
    def result(self) -> str:
        if self.in_time is None:
            return ""
        return "süre içinde" if self.in_time else "süre dolduktan sonra"

    def facts(self) -> dict[str, str]:
        """What the report model is given for the issue, to use as is."""
        facts = {
            "kural": self.period,
            "baslangic": f"{self.start.label}: {_day(self.start.value)}",
            "son_gun": f"yaklaşık {_day(self.last)}",
        }
        if self.act is not None:
            facts["islem"] = f"{self.act.label}: {_day(self.act.value)}"
            facts["sonuc"] = self.result
        return facts

    def sentence(self) -> AnswerSentence:
        text = (
            f"**{self.issue}:** {self.start.label} ({_day(self.start.value)}) tarihinden "
            f"itibaren {self.period}; son gün yaklaşık {_day(self.last)}"
        )
        if self.last.weekday() >= 5:
            text += " (hafta sonuna denk geliyor; süre ilk iş gününe uzayabilir)"
        text += "."
        if self.act is not None:
            label = self.act.label
            text += f" {label[:1].replace('i', 'İ').upper()}{label[1:]}: "
            text += f"{_day(self.act.value)}, {self.result}."
        return AnswerSentence(text=text, source_ids=list(self.source_ids))


def checked_deadline(
    issue: str,
    deadline: CaseDeadline | None,
    *,
    law: Sequence[EvidenceSource],
    files: Sequence[FileEvidenceSource],
) -> Deadline | None:
    """The issue's deadline if the file states its dates and the issue's law its limit."""
    if deadline is None:
        return None
    texts = [source.passage for source in files]
    start = verified_case_date(
        deadline.start_date, deadline.start_label or "sürenin başladığı olay", texts=texts
    )
    if start is None:
        return None
    pattern = period_pattern(deadline.amount, deadline.unit)
    stating = [source for source in law if pattern.search(fold(source.hit.record.text))]
    if not stating:
        return None
    act = verified_case_date(deadline.act_date, deadline.act_label or "işlem", texts=texts)
    if act is not None and act.value < start.value:
        act = None
    ids = [source.source_id for source in stating[:SOURCES_PER_FACT]]
    for case in (start, act):
        if case is not None:
            ids += [
                source.source_id for source in files if case.value in dates_in(source.passage)
            ][:SOURCES_PER_FACT]
    return Deadline(
        issue=issue,
        period=f"{deadline.amount} {deadline.unit}",
        start=start,
        last=last_day(start.value, deadline.amount, deadline.unit),
        act=act,
        source_ids=tuple(dict.fromkeys(ids)),
    )


def with_deadlines(answer: ChatAnswer, deadlines: Sequence[Deadline]) -> ChatAnswer:
    """The report with its time limits as worked out here, in place of any the model wrote."""
    heading = fold(DEADLINES_HEADING)
    blocks: list[AnswerBlock] = []
    skipping = False
    for block in answer.blocks:
        if block.kind == "heading":
            text = " ".join(sentence.text for sentence in block.sentences)
            skipping = fold(text).strip(" *#:.") == heading
        if not skipping:
            blocks.append(block)
    if deadlines:
        blocks.append(
            AnswerBlock(kind="heading", sentences=[AnswerSentence(text=DEADLINES_HEADING)])
        )
        blocks.append(
            AnswerBlock(
                kind="bullets",
                sentences=[
                    *(deadline.sentence() for deadline in deadlines),
                    AnswerSentence(text=APPROXIMATE_NOTE),
                ],
            )
        )
    return answer.model_copy(update={"blocks": blocks})
