from __future__ import annotations

import re
import unicodedata

TOKENIZER_VERSION = "tr-legal-v1"

_TOKEN_PATTERN = re.compile(
    r"""
    (?:e|k)\.\s*\d{4}/(?:\d+-)?\d+
    |\d{4}/(?:\d+-)?\d+
    |\d{1,4}/[a-zçğıöşü]
    |\d+(?:\.\d+)+
    |[a-zçğıöşü]+(?:['’][a-zçğıöşü]+)?
    |\d+
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def turkish_lower(value: str) -> str:
    return value.translate(str.maketrans({"I": "ı", "İ": "i"})).lower()


def normalize_for_lexical_search(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = turkish_lower(normalized)
    return " ".join(normalized.split())


def tokenize_legal_text(value: str) -> list[str]:
    normalized = normalize_for_lexical_search(value)
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        token = re.sub(r"\s+", "", match.group(0))
        tokens.append(token)
    return tokens


def canonical_token_string(value: str) -> str:
    return " ".join(tokenize_legal_text(value))
