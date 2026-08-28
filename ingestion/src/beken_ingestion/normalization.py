from __future__ import annotations

import hashlib
import re
import unicodedata

_HORIZONTAL_WHITESPACE = re.compile(r"[\t\f\v\u00a0 ]+")
_EXCESS_NEWLINES = re.compile(r"\n{3,}")


def normalize_legal_text(value: str) -> str:
    """Normalize transport artifacts without changing Turkish letters or legal numbering."""
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\u00ad", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_HORIZONTAL_WHITESPACE.sub(" ", line).strip() for line in value.split("\n")]
    return _EXCESS_NEWLINES.sub("\n\n", "\n".join(lines)).strip()


def stable_hash(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def normalized_identifier(value: str | None) -> str:
    if not value:
        return ""
    folded = unicodedata.normalize("NFKD", normalize_legal_text(value).casefold())
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    normalized = folded.translate(
        str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u"})
    )
    return re.sub(r"[^0-9a-z]+", "-", normalized).strip("-")
