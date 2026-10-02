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


_PREFIX_STEMMING = re.compile(r"prefix([1-9])")


def prefix_stem(token: str, letters: int) -> str:
    """A word cut to its first letters: "savunmasını" and "savunmam" are both "savun".

    Turkish stacks suffixes on a stem that rarely changes, so a fixed prefix is a simple
    stemmer for it. A suffix after an apostrophe goes ("kanun'un" → "kanun"); numbers and
    case numbers such as "e.2022/123" or "18/a" stay whole.
    """
    word = re.split(r"['’]", token, maxsplit=1)[0]
    return word[:letters] if word.isalpha() else token


def lexical_tokens(value: str, stemming: str | None = None) -> list[str]:
    """BM25 tokens of a text; `stemming` is None or "prefixN" (see `prefix_stem`)."""
    tokens = tokenize_legal_text(value)
    if not stemming:
        return tokens
    match = _PREFIX_STEMMING.fullmatch(stemming)
    if match is None:
        raise ValueError(f"Unknown lexical stemming: {stemming!r}")
    letters = int(match.group(1))
    return [prefix_stem(token, letters) for token in tokens]


def canonical_token_string(value: str) -> str:
    return " ".join(tokenize_legal_text(value))
