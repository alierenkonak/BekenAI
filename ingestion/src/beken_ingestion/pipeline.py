from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any

from beken_ingestion.database import CorpusRepository
from beken_ingestion.models import IngestionOutcome, RawDocument
from beken_ingestion.normalization import stable_hash
from beken_ingestion.parsers import parse_document
from beken_ingestion.storage import RawStorage

_MEDIA_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/xhtml+xml": ".html",
    "text/html": ".html",
    "text/plain": ".txt",
}

_TURKISH_ASCII_TRANSLATION = str.maketrans(
    {
        "ç": "c",
        "Ç": "C",
        "ğ": "g",
        "Ğ": "G",
        "ı": "i",
        "İ": "I",
        "ö": "o",
        "Ö": "O",
        "ş": "s",
        "Ş": "S",
        "ü": "u",
        "Ü": "U",
    }
)


def _slugify(value: str, fallback: str) -> str:
    transliterated = unicodedata.normalize(
        "NFKD", value.translate(_TURKISH_ASCII_TRANSLATION)
    ).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated.casefold()).strip("-")
    return slug[:120].rstrip("-") or fallback


def readable_storage_path(
    *,
    source_name: str,
    source_document_id: str | None,
    media_type: str,
    content_hash: str,
    metadata: dict[str, Any],
) -> str:
    source = _slugify(PurePosixPath(source_name).name, "source")
    source_kind = str(metadata.get("source_kind") or "")
    document_type = str(metadata.get("document_type") or "")
    storage_category = {
        "law": "kanun",
        "regulation": "yonetmelik",
        "court_decision": "yargitay",
        "course_note": "doktrin/ders-notu",
    }.get(document_type, source)
    if source_kind == "court_decision":
        authority = str(metadata.get("authority") or "").strip()
        chamber = str(metadata.get("chamber") or "").strip()
        heading = (
            chamber
            if authority and chamber.casefold().startswith(authority.casefold())
            else " ".join(part for part in (authority, chamber) if part)
        )
        references = " ".join(
            part
            for part in (
                f"E {metadata['case_number']}" if metadata.get("case_number") else "",
                f"K {metadata['decision_number']}"
                if metadata.get("decision_number")
                else "",
            )
            if part
        )
        label = " ".join(part for part in (heading, references) if part)
    else:
        label = str(metadata.get("title") or "").strip()
    label = label or source_document_id or "document"
    filename = _slugify(label, "document")
    extension = _MEDIA_EXTENSIONS.get(media_type.split(";", 1)[0].lower(), ".bin")
    return f"global/{storage_category}/{filename}--{content_hash[:12]}{extension}"


class IngestionPipeline:
    def __init__(self, repository: CorpusRepository, storage: RawStorage) -> None:
        self.repository = repository
        self.storage = storage

    def ingest(self, raw: RawDocument, corpus_version: str | None = None) -> IngestionOutcome:
        raw_hash = stable_hash(raw.content)
        storage_path = self.repository.artifact_storage_path(raw_hash)
        if storage_path is None:
            storage_path = readable_storage_path(
                source_name=raw.source_name,
                source_document_id=raw.source_document_id,
                media_type=raw.media_type,
                content_hash=raw_hash,
                metadata=raw.metadata,
            )
            self.storage.put_if_absent(storage_path, raw.content, raw.media_type)
        parsed = parse_document(raw)
        return self.repository.persist_document(
            raw,
            parsed,
            raw_hash=raw_hash,
            storage_path=storage_path,
            corpus_version=corpus_version,
        )

    def reparse(
        self,
        raw: RawDocument,
        storage_path: str,
        corpus_version: str,
    ) -> IngestionOutcome:
        """Parse an already stored immutable artifact without uploading it again."""
        raw_hash = stable_hash(raw.content)
        parsed = parse_document(raw)
        return self.repository.persist_document(
            raw,
            parsed,
            raw_hash=raw_hash,
            storage_path=storage_path,
            corpus_version=corpus_version,
        )
