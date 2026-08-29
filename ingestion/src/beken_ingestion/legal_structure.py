from __future__ import annotations

import re
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date

from beken_ingestion.models import LegalUnit, ProvisionEvent
from beken_ingestion.normalization import normalized_identifier, stable_hash

_ARTICLE = re.compile(
    r"(?im)^(?P<prefix>EK\s+GEÇİCİ|GEÇİCİ|EK|MÜKERRER)?\s*"
    r"M[ \t]*ADDE[ \t]*(?:\n[ \t]*)?"
    r"(?P<label>(?:\d+|[lIıİ]\d*?)(?:[ \t]+\d+)?(?:/[A-ZÇĞİÖŞÜ])?)"
    r"(?:"
    r"[ \t]+İLA[ \t]+(?P<range_end_ila>\d+(?:/[A-ZÇĞİÖŞÜ])?)"
    r"(?:[ \t]*[-–—][ \t]*|[ \t]*(?=\n|$)|[ \t]+(?=[A-ZÇĞİÖŞÜ]))"
    r"|[ \t]*[-–—][ \t]*(?P<range_end_dash>\d+(?:/[A-ZÇĞİÖŞÜ])?)"
    r"(?:[ \t]*[-–—][ \t]*|[ \t]*(?=\())"
    r"|[ \t]*\.?[ \t]*[-–—][ \t]*|[ \t]+(?=[A-ZÇĞİÖŞÜ])|[ \t]*(?=\n|$)|"
    r"[ \t]*(?=\((?:MÜLGA|EK|DEĞİŞİK|İPTAL)\b)"
    r")"
)
_UNNUMBERED_ARTICLE = re.compile(
    r"(?im)^(?P<prefix>EK\s+GEÇİCİ|GEÇİCİ|EK)\s+MADDE"
    r"[ \t]*[-–—][ \t]*"
)
_HEADING = re.compile(
    r"(?im)^(?P<label>(?:[A-ZÇĞİÖŞÜİ]+|[IVXLCDM]+|\d+)\s+)"
    r"(?P<kind>KİTAP|KISIM|BÖLÜM|AYIRIM)\s*$"
)
_ANNEX = re.compile(
    r"(?im)^(?P<label>(?:EK(?:[-– ]?\d+)?|\(?[IVXLCDM]+\)?\s+SAYILI\s+"
    r"(?:CETVEL|LİSTE)|\d+\s+SAYILI\s+TARİFE))\b.*$"
)
_SUPPLEMENT = re.compile(
    r"(?im)^\s*[^\n]{0,100}?(?P<law_number>\d{3,4})\s+SAYILI\s+"
    r"(?:ANA\s+)?KANUNA\s+"
    r"(?P<kind>İŞLENEMEYEN\s+(?:GEÇİCİ\s+MADDELER|"
    r"KANUN\s+HÜKMÜNDE\s+KARARNAME\s+HÜKÜMLERİ?|"
    r"KANUN\s+HÜKÜMLERİ?|HÜKÜMLERİ?)|"
    r"EK\s+VE\s+DEĞİŞİKLİK\s+GETİREN\s+MEVZUATIN)"
    r"[^\n]*$"
)
_TERMINAL_REFERENCE = re.compile(
    r"(?im)^\s*(?P<law_number>\d{3,4})\s+SAYILI\s+KANUNDA\s+"
    r"(?P<kind>EK\s+VE\s+DEĞİŞİKLİK\s+YAPAN\s+MEVZUATIN)\s+"
    r"[^\n]*(?:\n[^\n]*)?\bLİSTE\s*$"
)
_PARAGRAPH = re.compile(r"(?m)^\s*\((?P<label>\d+)\)\s+")
_ITEM = re.compile(r"(?m)^\s*(?P<label>[a-zçğıöşü])\)\s+")
_SUBITEM_NUMBER = re.compile(r"(?m)^\s*(?P<label>\d+)\)\s+")
_SUBITEM_ROMAN = re.compile(r"(?m)^\s*(?P<label>[ivxlcdm]+)\)\s+")
_ANNOTATION = re.compile(
    r"(?P<body>(?:Ek(?:\s+(?:fıkra|cümle))?|Değişik(?:\s+(?:[^:();]{1,40}))?|"
    r"Mülga|İptal(?:\s+(?:[^:();]{1,40}))?|Yeniden\s+düzenleme)"
    r"\s*:[^;()]{3,700})",
    re.IGNORECASE,
)
_AYM_ANNOTATION = re.compile(
    r"\((?P<body>Anayasa\s+Mahkemesi(?:nin|'nin)[^()]{3,700}iptal[^()]{0,300})\)",
    re.IGNORECASE,
)
_AYM_NOTE = re.compile(
    r"(?P<body>Anayasa\s+Mahkemesi(?:nin|’nin|'nin)"
    r"(?:(?!Anayasa\s+Mahkemesi)[\s\S]){0,450}?"
    r"E\.?\s*[:：]?\s*\d{4}/\d+"
    r"(?:(?!Anayasa\s+Mahkemesi)[\s\S]){0,100}?"
    r"K\.?\s*[:：]?\s*\d{4}/\d+"
    r"(?:(?!Anayasa\s+Mahkemesi)[\s\S]){0,700}?ipta\s*l"
    r"(?:(?!Anayasa\s+Mahkemesi)[\s\S]){0,350}?(?:\."
    r"(?:\s*Bu\s+Karar(?:(?!Anayasa\s+Mahkemesi)[\s\S]){0,350}?"
    r"yürürlüğe\s+gir[^.]*\.)?|\Z))",
    re.IGNORECASE,
)
_LAW_REFERENCE = re.compile(r"-(?P<law>\d{4})/(?P<article>\d+)\s*(?:md\.?|maddesi)", re.I)
_CASE_REFERENCE = re.compile(
    r"E\.?\s*[:：]?\s*(?P<case>\d{4}/\d+).*?"
    r"K\.?\s*[:：]?\s*(?P<decision>\d{4}/\d+)",
    re.I | re.S,
)
_DATE = re.compile(r"(?<!\d)(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})(?!\d)")
_GAZETTE_DATE = re.compile(
    r"Resm[iî]\s+Gazete(?:(?!\bay\s+sonra\b)[^\d]){0,100}"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)
_EXPLICIT_EFFECTIVE_DATE = re.compile(
    r"ay\s+sonra\s*\(\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*\)"
    r"[^.]{0,60}yürürlüğe\s+gir",
    re.IGNORECASE,
)
_MONTH_DELAY = re.compile(
    r"(?P<months>\d+|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|on iki)\s+ay\s+sonra",
    re.IGNORECASE,
)
_MONTH_WORDS = {
    "bir": 1,
    "iki": 2,
    "üç": 3,
    "dört": 4,
    "beş": 5,
    "altı": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
    "on iki": 12,
}

_ARTICLE_TYPES = {
    "": "article",
    "ek": "additional_article",
    "gecici": "temporary_article",
    "ek-gecici": "additional_temporary_article",
    "mukerrer": "repeated_article",
}
_HEADING_TYPES = {"KİTAP": "book", "KISIM": "part", "BÖLÜM": "chapter", "AYIRIM": "section"}
_CONTAINER_TYPES = {*_ARTICLE_TYPES.values(), "annex"}


@dataclass(frozen=True)
class _Marker:
    start: int
    header_end: int
    unit_type: str
    label: str | None
    heading: str | None
    metadata: dict[str, object] = field(default_factory=dict)


def _canonical_article_label(value: str) -> tuple[str, bool]:
    canonical = re.sub(r"[ \t]+", "", value)
    canonical = re.sub(r"^[lIıİ](?=\d|$)", "1", canonical)
    return canonical, canonical != value


def _range_labels(start: str, end: str) -> list[str]:
    start_match = re.fullmatch(r"(?P<number>\d+)(?:/(?P<suffix>[A-ZÇĞİÖŞÜ]))?", start)
    end_match = re.fullmatch(r"(?P<number>\d+)(?:/(?P<suffix>[A-ZÇĞİÖŞÜ]))?", end)
    if not start_match or not end_match:
        return []
    start_number = int(start_match.group("number"))
    end_number = int(end_match.group("number"))
    invalid_range = (
        start_match.group("suffix")
        or end_number < start_number
        or end_number - start_number > 2_000
    )
    if invalid_range:
        return []
    labels = [str(number) for number in range(start_number, end_number + 1)]
    if end_match.group("suffix"):
        labels.append(f"{end_number}/{end_match.group('suffix')}")
    return labels


def _page_for_offset(page_spans: list[tuple[int, int, int | None]], offset: int) -> int | None:
    for start, end, page_number in page_spans:
        if start <= offset < end:
            return page_number
    return None


def _parse_date(match: re.Match[str] | None) -> date | None:
    if not match:
        return None
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def _date_from_text(value: str | None) -> date | None:
    return _parse_date(_DATE.search(value or ""))


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _key_part(value: str | None, fallback: str) -> str:
    return normalized_identifier(value or fallback) or fallback


def _heading_after(text: str, offset: int) -> str | None:
    for line in text[offset : offset + 240].splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if len(candidate) > 160 or _ARTICLE.match(candidate) or _HEADING.match(candidate):
            return None
        return candidate
    return None


def _heading_before(text: str, offset: int) -> str | None:
    lines = [line.strip() for line in text[max(0, offset - 240) : offset].splitlines()]
    for candidate in reversed(lines):
        if not candidate:
            continue
        if len(candidate) > 160 or candidate[-1:] in {".", ";", ":", ")"}:
            return None
        if _ARTICLE.match(candidate) or _HEADING.match(candidate):
            return None
        return candidate
    return None


def _primary_markers(text: str) -> list[_Marker]:
    markers: list[_Marker] = []
    supplement_candidates = [
        match
        for pattern in (_SUPPLEMENT, _TERMINAL_REFERENCE)
        if (match := pattern.search(text)) is not None
    ]
    supplement = min(supplement_candidates, key=lambda match: match.start(), default=None)
    core_end = supplement.start() if supplement else len(text)
    for match in _HEADING.finditer(text):
        if match.start() >= core_end:
            continue
        kind = match.group("kind").upper()
        markers.append(
            _Marker(
                match.start(),
                match.end(),
                _HEADING_TYPES[kind],
                match.group("label").strip(),
                _heading_after(text, match.end()),
            )
        )
    for match in _ARTICLE.finditer(text):
        if match.start() >= core_end:
            continue
        prefix = normalized_identifier(match.group("prefix") or "")
        label, number_repaired = _canonical_article_label(match.group("label"))
        raw_range_end = match.group("range_end_ila") or match.group("range_end_dash")
        range_end = _canonical_article_label(raw_range_end)[0] if raw_range_end else None
        metadata: dict[str, object] = {}
        display_label = label
        if number_repaired:
            metadata["source_label"] = match.group("label")
            metadata["number_repaired"] = True
        represented_range = _range_labels(label, range_end) if range_end else []
        if range_end and represented_range:
            display_label = f"{label}-{range_end}"
            metadata.update(
                {
                    "range_start": label,
                    "range_end": range_end,
                    "represented_article_labels": represented_range,
                }
            )
        markers.append(
            _Marker(
                match.start(),
                match.end(),
                _ARTICLE_TYPES[prefix],
                display_label,
                _heading_before(text, match.start()),
                metadata,
            )
        )
    for match in _UNNUMBERED_ARTICLE.finditer(text):
        if match.start() >= core_end:
            continue
        prefix = normalized_identifier(match.group("prefix") or "")
        markers.append(
            _Marker(
                match.start(),
                match.end(),
                _ARTICLE_TYPES[prefix],
                None,
                _heading_before(text, match.start()),
                {"unnumbered_article": True},
            )
        )
    for match in _ANNEX.finditer(text):
        if match.start() >= core_end:
            continue
        markers.append(_Marker(match.start(), match.end(), "annex", match.group("label"), None))
    if supplement:
        markers.append(
            _Marker(
                supplement.start(),
                supplement.end(),
                "annex",
                "supplement",
                supplement.group(0).strip(),
                {
                    "supplement_type": normalized_identifier(supplement.group("kind")),
                    "law_number": supplement.group("law_number"),
                },
            )
        )
    markers.sort(key=lambda marker: (marker.start, -marker.header_end))
    deduplicated: list[_Marker] = []
    for marker in markers:
        if deduplicated and marker.start == deduplicated[-1].start:
            if marker.unit_type in _CONTAINER_TYPES:
                deduplicated[-1] = marker
            continue
        deduplicated.append(marker)
    return deduplicated


def _child_markers(text: str, start: int, end: int) -> list[_Marker]:
    local = text[start:end]
    candidates: list[_Marker] = []
    for match in _PARAGRAPH.finditer(local):
        candidates.append(
            _Marker(
                start + match.start(),
                start + match.end(),
                "paragraph",
                match.group("label"),
                None,
            )
        )
    for match in _ITEM.finditer(local):
        candidates.append(
            _Marker(start + match.start(), start + match.end(), "item", match.group("label"), None)
        )
    candidates.sort(key=lambda marker: (marker.start, marker.unit_type))

    result: list[_Marker] = []
    item_seen = False
    for marker in candidates:
        if result and marker.start == result[-1].start:
            continue
        result.append(marker)
        item_seen = item_seen or marker.unit_type == "item"

    if item_seen:
        for pattern in (_SUBITEM_NUMBER, _SUBITEM_ROMAN):
            for match in pattern.finditer(local):
                absolute_start = start + match.start()
                if any(marker.start == absolute_start for marker in result):
                    continue
                if any(
                    marker.unit_type == "item" and marker.start < absolute_start
                    for marker in result
                ):
                    result.append(
                        _Marker(
                            absolute_start,
                            start + match.end(),
                            "subitem",
                            match.group("label"),
                            None,
                        )
                    )
    return sorted(result, key=lambda marker: marker.start)


def _build_unit(
    *,
    index: int,
    marker: _Marker,
    end: int,
    text: str,
    parent_key: str | None,
    parent_path: tuple[str, ...],
    page_spans: list[tuple[int, int, int | None]],
    extraction_method: str,
    confidence: float,
    sibling_number: int,
    metadata: dict[str, object] | None = None,
) -> LegalUnit | None:
    passage = text[marker.start:end].strip()
    if not passage:
        return None
    raw = text[marker.start:end]
    leading = len(raw) - len(raw.lstrip())
    char_start = marker.start + leading
    char_end = char_start + len(passage)
    key_label = _key_part(marker.label, str(sibling_number))
    key = (
        f"{parent_key}/{marker.unit_type}-{key_label}"
        if parent_key
        else f"{marker.unit_type}-{key_label}"
    )
    path_label = marker.label or str(sibling_number)
    unit_path = (*parent_path, f"{marker.unit_type}:{path_label}")
    unit_metadata = {**marker.metadata, **(metadata or {})}
    if marker.unit_type == "annex":
        unit_metadata["table_parse_status"] = "unparsed"
    return LegalUnit(
        unit_index=index,
        unit_key=key,
        parent_key=parent_key,
        unit_path=unit_path,
        unit_type=marker.unit_type,
        label=marker.label,
        heading=marker.heading,
        text=passage,
        page_number=_page_for_offset(page_spans, char_start),
        char_start=char_start,
        char_end=char_end,
        content_hash=stable_hash(passage),
        extraction_method=extraction_method,
        confidence=confidence,
        metadata=unit_metadata,
    )


def _unique_unit(unit: LegalUnit, key_counts: dict[str, int]) -> LegalUnit:
    occurrence = key_counts.get(unit.unit_key, 0)
    key_counts[unit.unit_key] = occurrence + 1
    if occurrence == 0:
        return unit
    suffix = occurrence + 1
    metadata = dict(unit.metadata)
    metadata["repeated_label_occurrence"] = suffix
    return replace(
        unit,
        unit_key=f"{unit.unit_key}~{suffix}",
        unit_path=(*unit.unit_path[:-1], f"{unit.unit_path[-1]}#{suffix}"),
        review_status="needs_review",
        metadata=metadata,
    )


def _target_type(annotation: str) -> str:
    normalized = normalized_identifier(annotation)
    if "ibare" in normalized:
        return "phrase"
    if "cumle" in normalized:
        return "sentence"
    if "fikra" in normalized:
        return "paragraph"
    if "bent" in normalized:
        return "item"
    if "madde" in normalized:
        return "article"
    return "unit"


def _event_type(annotation: str) -> str:
    normalized = normalized_identifier(annotation)
    if "anayasa-mahkemesi" in normalized or normalized.startswith("iptal"):
        return "annulled"
    if normalized.startswith("mulga"):
        return "repealed"
    if normalized.startswith("ek"):
        return "added"
    return "amended"


def _events(text: str, units: list[LegalUnit]) -> tuple[ProvisionEvent, ...]:
    candidates = [
        match
        for pattern in (_ANNOTATION, _AYM_ANNOTATION, _AYM_NOTE)
        for match in pattern.finditer(text)
    ]
    matches: list[re.Match[str]] = []
    for match in sorted(candidates, key=lambda item: (item.start(), -(item.end() - item.start()))):
        if any(
            match.start() < selected.end() and match.end() > selected.start()
            for selected in matches
        ):
            continue
        matches.append(match)
    events: list[ProvisionEvent] = []
    for match in matches:
        annotation = match.group("body").strip()
        containers = [
            unit for unit in units if unit.char_start <= match.start() < unit.char_end
        ]
        linked = (
            min(containers, key=lambda unit: unit.char_end - unit.char_start)
            if containers
            else None
        )
        law = _LAW_REFERENCE.search(annotation)
        case = _CASE_REFERENCE.search(annotation)
        first_date = _DATE.search(annotation)
        gazette_match = _GAZETTE_DATE.search(annotation)
        gazette_date = _date_from_text(gazette_match.group("date")) if gazette_match else None
        delay_match = _MONTH_DELAY.search(annotation)
        explicit_effective_match = _EXPLICIT_EFFECTIVE_DATE.search(annotation)
        delay_months = None
        if delay_match:
            delay_value = delay_match.group("months").casefold()
            delay_months = int(delay_value) if delay_value.isdigit() else _MONTH_WORDS[delay_value]
        explicit_effective_date = (
            _date_from_text(explicit_effective_match.group("date"))
            if explicit_effective_match
            else None
        )
        effective_from = explicit_effective_date or (
            _add_months(gazette_date, delay_months)
            if gazette_date and delay_months is not None
            else None
        )
        is_aym = "anayasa-mahkemesi" in normalized_identifier(annotation)
        confidence = (
            0.9
            if linked and (law or case or annotation.casefold().startswith("mülga"))
            else 0.7
        )
        events.append(
            ProvisionEvent(
                event_index=len(events),
                legal_unit_key=linked.unit_key if linked else None,
                event_type=_event_type(annotation),
                target_type=_target_type(annotation),
                authority="Anayasa Mahkemesi" if is_aym else "Türkiye Büyük Millet Meclisi",
                source_law_number=law.group("law") if law else None,
                source_law_article=law.group("article") if law else None,
                case_number=case.group("case") if case else None,
                decision_number=case.group("decision") if case else None,
                event_date=_parse_date(first_date),
                official_gazette_date=gazette_date,
                effective_from=effective_from,
                target_char_start=match.start(),
                target_char_end=match.end(),
                raw_annotation=annotation,
                confidence=confidence,
                review_status="accepted" if confidence >= 0.9 else "needs_review",
                metadata={
                    "partial_or_delayed_effect_requires_review": is_aym
                    and (_target_type(annotation) != "unit" or delay_months is not None),
                    "delay_months": delay_months,
                },
            )
        )
    return tuple(events)


def parse_legal_structure(
    text: str,
    page_spans: list[tuple[int, int, int | None]],
    extraction_method: str,
    confidence: float,
) -> tuple[tuple[LegalUnit, ...], tuple[ProvisionEvent, ...]]:
    markers = _primary_markers(text)
    if not markers:
        return (), ()

    if markers[0].start > 0:
        markers.insert(0, _Marker(0, 0, "metadata", "document", None))

    units: list[LegalUnit] = []
    key_counts: dict[str, int] = {}
    heading_stack: list[LegalUnit] = []
    for marker_index, marker in enumerate(markers):
        end = markers[marker_index + 1].start if marker_index + 1 < len(markers) else len(text)
        if marker.unit_type in _HEADING_TYPES.values():
            level = ["book", "part", "chapter", "section"].index(marker.unit_type)
            hierarchy = ["book", "part", "chapter", "section"]
            heading_stack = [
                unit for unit in heading_stack if hierarchy.index(unit.unit_type) < level
            ]
            parent = heading_stack[-1] if heading_stack else None
        elif marker.unit_type == "metadata":
            parent = None
        else:
            parent = heading_stack[-1] if heading_stack else None

        unit = _build_unit(
            index=len(units),
            marker=marker,
            end=end,
            text=text,
            parent_key=parent.unit_key if parent else None,
            parent_path=parent.unit_path if parent else (),
            page_spans=page_spans,
            extraction_method=extraction_method,
            confidence=confidence,
            sibling_number=marker_index,
        )
        if not unit:
            continue
        unit = _unique_unit(unit, key_counts)
        units.append(unit)
        if marker.unit_type in _HEADING_TYPES.values():
            heading_stack.append(unit)

        if marker.unit_type not in _ARTICLE_TYPES.values():
            continue
        children = _child_markers(text, marker.header_end, end)
        latest_paragraph: LegalUnit | None = None
        latest_item: LegalUnit | None = None
        for child_index, child in enumerate(children):
            child_end = children[child_index + 1].start if child_index + 1 < len(children) else end
            if child.unit_type == "paragraph":
                child_parent = unit
                latest_item = None
            elif child.unit_type == "item":
                child_parent = latest_paragraph or unit
            else:
                child_parent = latest_item
                if child_parent is None:
                    continue
            child_unit = _build_unit(
                index=len(units),
                marker=child,
                end=child_end,
                text=text,
                parent_key=child_parent.unit_key,
                parent_path=child_parent.unit_path,
                page_spans=page_spans,
                extraction_method=extraction_method,
                confidence=confidence,
                sibling_number=child_index,
            )
            if not child_unit:
                continue
            child_unit = _unique_unit(child_unit, key_counts)
            units.append(child_unit)
            if child.unit_type == "paragraph":
                latest_paragraph = child_unit
            elif child.unit_type == "item":
                latest_item = child_unit

    return tuple(units), _events(text, units)


def audit_article_structure(
    units: tuple[LegalUnit, ...], expectations: dict[str, object]
) -> dict[str, object]:
    articles = [unit for unit in units if unit.unit_type == "article"]
    represented: list[str] = []
    explicit_labels: list[str] = []
    for unit in articles:
        range_labels = unit.metadata.get("represented_article_labels")
        if isinstance(range_labels, list) and range_labels:
            represented.extend(str(label) for label in range_labels)
        elif unit.label:
            represented.append(unit.label)
        if unit.label:
            explicit_labels.append(unit.label)

    start = int(expectations.get("required_numeric_start", 1))
    end = int(expectations.get("required_numeric_end", 0))
    required = {str(number) for number in range(start, end + 1)} if end >= start else set()
    required.update(str(label) for label in expectations.get("required_labels", []))
    represented_set = set(represented)
    duplicates = sorted(
        label for label, count in Counter(explicit_labels).items() if count > 1
    )
    unexpected_numeric = sorted(
        {
            label
            for label in represented_set
            if label.isdigit() and end >= start and not start <= int(label) <= end
        },
        key=int,
    )
    missing = sorted(
        required - represented_set,
        key=lambda label: (int(label.split("/", 1)[0]), label),
    )
    passed = not missing and not duplicates and not unexpected_numeric
    return {
        "status": "passed" if passed else "failed",
        "required_count": len(required),
        "represented_count": len(represented_set),
        "missing_labels": missing,
        "duplicate_explicit_labels": duplicates,
        "unexpected_numeric_labels": unexpected_numeric,
    }
