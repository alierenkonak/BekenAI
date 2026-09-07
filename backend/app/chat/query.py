from __future__ import annotations

import re

_LEGAL_TERMS = {
    "alacak",
    "arabulucu",
    "fesih",
    "ihbar",
    "işçi",
    "işveren",
    "işe iade",
    "kanun",
    "kıdem",
    "madde",
    "sözleşme",
    "tazminat",
    "ücret",
    "yargıtay",
    "zamanaşımı",
}


def derive_retrieval_query(message: str, *, maximum: int = 500) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= maximum:
        return normalized
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", normalized) if item.strip()]
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (
            "?" in item[1],
            sum(term in item[1].casefold() for term in _LEGAL_TERMS),
            item[0],
        ),
        reverse=True,
    )
    selected: list[tuple[int, str]] = []
    used = 0
    for position, sentence in ranked:
        required = len(sentence) + (1 if selected else 0)
        if used + required <= maximum:
            selected.append((position, sentence))
            used += required
    query = " ".join(sentence for _, sentence in sorted(selected))
    if len(query) < 3:
        query = normalized[:maximum]
    return query
