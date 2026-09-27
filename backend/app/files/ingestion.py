from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID, uuid4

from beken_retrieval.dense import EncodedBatch
from beken_retrieval.model_catalog import ModelSpec
from beken_retrieval.remote_inference import RemoteInferenceClient

from app.core.repository import ConflictError
from app.files.chunking import FileChunk, chunk_document
from app.files.extraction import ExtractionError, extract_document
from app.files.vectors import PrivateChunkPoint, PrivateFileVectorStore

logger = logging.getLogger("bekenai.files")

# The model service accepts at most 32 texts per request; 16 keeps each call short
# enough that progress moves visibly and a heartbeat lands well before the stale window.
EMBEDDING_BATCH_SIZE = 16


class PassageEmbedder(Protocol):
    model_key: str
    dimensions: int

    def embed_passages(self, texts: Sequence[str]) -> EncodedBatch: ...


class RemotePassageEmbedder:
    def __init__(self, spec: ModelSpec, client: RemoteInferenceClient) -> None:
        if spec.dimensions is None:
            raise ValueError("Embedding model metadata is incomplete")
        self.spec = spec
        self.client = client
        self.model_key = spec.key
        self.dimensions = spec.dimensions

    def embed_passages(self, texts: Sequence[str]) -> EncodedBatch:
        return self.client.embed(spec=self.spec, texts=texts, input_type="passage")


def embedding_text(document_title: str, chunk: FileChunk) -> str:
    """The file name and section often carry the meaning a bare passage lacks."""
    parts = [f"Belge: {document_title}"]
    if chunk.section_title and not chunk.text.startswith(chunk.section_title):
        parts.append(f"Bölüm: {chunk.section_title}")
    parts.append(chunk.text)
    return "\n".join(parts)


def document_title(original_name: str) -> str:
    stem = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    return stem.replace("_", " ").strip() or original_name


class FileIngestionService:
    def __init__(
        self,
        *,
        repository: Any,
        storage: Any,
        embedder: PassageEmbedder,
        vectors: PrivateFileVectorStore,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.embedder = embedder
        self.vectors = vectors
        self.batch_size = batch_size

    async def ingest(self, job: dict[str, Any]) -> None:
        file = await self.repository.get_worker_file(job["subject_id"])
        if file["status"] != "indexing":
            raise ConflictError("file_not_indexing")
        data = await self.storage.download(
            file["storage_path"],
            maximum_bytes=file["verified_size_bytes"] or file["expected_size_bytes"],
        )
        if file["content_hash"] and hashlib.sha256(data).hexdigest() != file["content_hash"]:
            raise ExtractionError("file_content_changed")
        media_type = file["detected_media_type"] or file["declared_media_type"]
        document = await asyncio.to_thread(extract_document, data, media_type)
        chunks = await asyncio.to_thread(chunk_document, document)
        if not chunks:
            raise ExtractionError("empty_document")
        await self._progress(
            job,
            file,
            chunks_done=0,
            chunks_total=len(chunks),
            page_count=document.page_count,
            unreadable_page_count=document.unreadable_pages,
        )

        await asyncio.to_thread(self.vectors.ensure_collection)
        # A retried job starts from a clean slate instead of merging with a partial run.
        await asyncio.to_thread(
            self.vectors.delete_file, workspace_id=file["workspace_id"], file_id=file["id"]
        )
        chunk_ids = [uuid4() for _ in chunks]
        title = document_title(file["original_name"])
        try:
            # Similar lengths per batch keep padding, and so CPU time, to a minimum.
            order = sorted(range(len(chunks)), key=lambda position: len(chunks[position].text))
            done = 0
            for start in range(0, len(order), self.batch_size):
                batch = order[start : start + self.batch_size]
                encoded = await asyncio.to_thread(
                    self.embedder.embed_passages,
                    [embedding_text(title, chunks[position]) for position in batch],
                )
                points = [
                    PrivateChunkPoint(
                        chunk_id=chunk_ids[position],
                        chunk_index=chunks[position].index,
                        vector=vector,
                        truncated=truncated,
                        page_start=chunks[position].page_start,
                        page_end=chunks[position].page_end,
                    )
                    for position, vector, truncated in zip(
                        batch, encoded.vectors, encoded.truncated, strict=True
                    )
                ]
                await asyncio.to_thread(
                    self.vectors.upsert,
                    workspace_id=file["workspace_id"],
                    file_id=file["id"],
                    case_id=file["case_id"],
                    conversation_id=file["conversation_id"],
                    embedding_model=self.embedder.model_key,
                    points=points,
                )
                done += len(batch)
                await self._progress(job, file, chunks_done=done)
            await self.repository.complete_file_indexing(
                job["id"],
                file["id"],
                chunks=chunks,
                chunk_ids=chunk_ids,
                embedding_model=self.embedder.model_key,
                page_count=document.page_count,
                unreadable_page_count=document.unreadable_pages,
            )
        except Exception:
            await self._discard_vectors(file["workspace_id"], file["id"])
            raise

    async def _progress(self, job: dict[str, Any], file: dict[str, Any], **values: Any) -> None:
        if not await self.repository.report_file_progress(job["id"], file["id"], **values):
            # Deleted (or otherwise moved on) while we were working: stop quietly.
            raise ConflictError("file_not_indexing")

    async def _discard_vectors(self, workspace_id: UUID, file_id: UUID) -> None:
        try:
            await asyncio.to_thread(
                self.vectors.delete_file, workspace_id=workspace_id, file_id=file_id
            )
        except Exception as exc:
            # The next attempt or the deletion job clears them; never mask the real error.
            logger.warning("Private vector cleanup skipped (%s)", type(exc).__name__)
