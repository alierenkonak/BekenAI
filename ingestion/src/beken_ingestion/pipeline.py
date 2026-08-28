from __future__ import annotations

from pathlib import PurePosixPath

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


class IngestionPipeline:
    def __init__(self, repository: CorpusRepository, storage: RawStorage) -> None:
        self.repository = repository
        self.storage = storage

    def ingest(self, raw: RawDocument, corpus_version: str | None = None) -> IngestionOutcome:
        raw_hash = stable_hash(raw.content)
        extension = _MEDIA_EXTENSIONS.get(raw.media_type.split(";", 1)[0].lower(), ".bin")
        source = PurePosixPath(raw.source_name).name.casefold().replace(" ", "-")
        storage_path = f"global/{source}/{raw_hash[:2]}/{raw_hash}{extension}"
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
