from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

import httpx
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

# Private chunks never share a collection with the global corpus (ADR 0002). Every
# point carries its workspace, and every read or delete filters on it.
PRIVATE_FILES_COLLECTION = "beken_private_files_bge_m3_v1"
_SCOPE_FIELDS = ("workspace_id", "file_id", "case_id", "conversation_id")


class VectorStoreUnavailable(RuntimeError):
    """A retryable Qdrant transport or server failure."""


@dataclass(frozen=True)
class PrivateChunkPoint:
    chunk_id: UUID
    chunk_index: int
    vector: list[float]
    truncated: bool
    page_start: int | None
    page_end: int | None


class PrivateFileVectorStore:
    def __init__(
        self,
        client: QdrantClient,
        *,
        dimensions: int,
        collection: str = PRIVATE_FILES_COLLECTION,
    ) -> None:
        if not collection.startswith("beken_private_"):
            raise ValueError("Private file vectors must use a beken_private_* collection")
        self.client = client
        self.dimensions = dimensions
        self.collection = collection

    def ensure_collection(self) -> None:
        with _transient():
            if self.client.collection_exists(self.collection):
                return
            try:
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=self.dimensions, distance=models.Distance.COSINE
                    ),
                )
            except UnexpectedResponse:
                # Another worker created it between the check and the create.
                if not self.client.collection_exists(self.collection):
                    raise
                return
            for field in _SCOPE_FIELDS:
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=models.KeywordIndexParams(
                        type=models.KeywordIndexType.KEYWORD,
                        is_tenant=field == "workspace_id",
                    ),
                )

    def upsert(
        self,
        *,
        workspace_id: UUID,
        file_id: UUID,
        case_id: UUID | None,
        conversation_id: UUID | None,
        embedding_model: str,
        points: Sequence[PrivateChunkPoint],
    ) -> None:
        if not points:
            return
        scope = {
            "workspace_id": str(workspace_id),
            "file_id": str(file_id),
            "case_id": str(case_id) if case_id else None,
            "conversation_id": str(conversation_id) if conversation_id else None,
        }
        with _transient():
            self.client.upsert(
                collection_name=self.collection,
                points=[
                    models.PointStruct(
                        id=str(point.chunk_id),
                        vector=point.vector,
                        payload={
                            **scope,
                            "chunk_index": point.chunk_index,
                            "page_start": point.page_start,
                            "page_end": point.page_end,
                            "embedding_model": embedding_model,
                            "embedding_truncated": point.truncated,
                        },
                    )
                    for point in points
                ],
                wait=True,
            )

    def delete_file(self, *, workspace_id: UUID, file_id: UUID) -> None:
        with _transient():
            if not self.client.collection_exists(self.collection):
                return
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(
                    filter=_filter(workspace_id=workspace_id, file_id=file_id)
                ),
                wait=True,
            )

    def count_file_points(self, *, workspace_id: UUID, file_id: UUID) -> int:
        with _transient():
            if not self.client.collection_exists(self.collection):
                return 0
            return self.client.count(
                collection_name=self.collection,
                count_filter=_filter(workspace_id=workspace_id, file_id=file_id),
                exact=True,
            ).count


def _filter(**conditions: UUID) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(key=key, match=models.MatchValue(value=str(value)))
            for key, value in conditions.items()
        ]
    )


@contextmanager
def _transient() -> Iterator[None]:
    """Map Qdrant outages to one retryable error without leaking URLs or payloads."""
    try:
        yield
    except UnexpectedResponse as exc:
        if exc.status_code == 429 or (exc.status_code or 0) >= 500:
            raise VectorStoreUnavailable("vector_store_temporarily_unavailable") from None
        raise
    except (ResponseHandlingException, httpx.TransportError, ConnectionError):
        raise VectorStoreUnavailable("vector_store_temporarily_unavailable") from None
