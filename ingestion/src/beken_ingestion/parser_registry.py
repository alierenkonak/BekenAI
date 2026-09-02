from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from beken_ingestion.models import ParsedDocument, RawDocument, TextPage

DocumentParser = Callable[[RawDocument, list[TextPage], str, str], ParsedDocument]
ParserT = TypeVar("ParserT")


class UnsupportedDocumentType(ValueError):
    """Raised when no explicit parser is registered for a legal document type."""


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[tuple[str, str], DocumentParser] = {}

    def register(
        self, source_kind: str, document_type: str
    ) -> Callable[[DocumentParser], DocumentParser]:
        key = (source_kind, document_type)

        def decorator(parser: DocumentParser) -> DocumentParser:
            if key in self._parsers:
                raise ValueError(f"Parser already registered for {key!r}")
            self._parsers[key] = parser
            return parser

        return decorator

    def resolve(self, source_kind: str, document_type: str) -> DocumentParser:
        try:
            return self._parsers[(source_kind, document_type)]
        except KeyError as exc:
            raise UnsupportedDocumentType(
                "unsupported_document_type: "
                f"source_kind={source_kind!r}, document_type={document_type!r}"
            ) from exc

    @property
    def supported_types(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._parsers))
