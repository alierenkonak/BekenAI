from __future__ import annotations

import re
from collections.abc import Sequence

from qdrant_client import QdrantClient, models

from beken_retrieval.dense import DenseEncoder
from beken_retrieval.filters import matches_filters
from beken_retrieval.models import ChunkRecord, SearchFilters, SearchHit
from beken_retrieval.postgres import PostgresCorpusRepository
from beken_retrieval.scope import RetrievalScope


def collection_name(
    *,
    domain: str,
    corpus_version: str,
    model_key: str,
    index_version: str | None = None,
    channel: str = "primary",
    prefix: str = "beken_global",
) -> str:
    lane = "" if channel == "primary" else f"_{channel}"
    value = f"{prefix}_{domain}{lane}_{corpus_version}_{model_key}"
    if index_version:
        value = f"{value}_{index_version}"
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value)[:255]


def active_alias(
    domain: str, channel: str = "primary", prefix: str = "beken_global"
) -> str:
    lane = "" if channel == "primary" else f"_{channel}"
    return f"{prefix}_{domain}{lane}_active"


class QdrantIndexer:
    def __init__(self, client: QdrantClient) -> None:
        self.client = client

    def build_immutable(
        self,
        *,
        collection: str,
        records: Sequence[ChunkRecord],
        encoder: DenseEncoder,
        batch_size: int = 32,
    ) -> dict[str, int]:
        if not records:
            raise ValueError("Cannot build an empty Qdrant collection")
        if self.client.collection_exists(collection):
            raise FileExistsError(f"Immutable Qdrant collection already exists: {collection}")
        self.client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(
                size=encoder.dimensions,
                distance=models.Distance.COSINE,
            ),
        )
        truncated_count = 0
        indexed_count = 0
        try:
            for start in range(0, len(records), batch_size):
                batch = list(records[start : start + batch_size])
                encoded = encoder.encode_records(batch)
                truncated_count += sum(encoded.truncated)
                points = []
                for record, vector, truncated in zip(
                    batch, encoded.vectors, encoded.truncated, strict=True
                ):
                    payload = record.to_dict()
                    payload.pop("text", None)
                    payload["embedding_truncated"] = truncated
                    payload["embedding_model"] = encoder.model_key
                    points.append(
                        models.PointStruct(
                            id=record.chunk_id,
                            vector=vector,
                            payload=payload,
                        )
                    )
                self.client.upsert(
                    collection_name=collection,
                    points=points,
                    wait=True,
                )
                indexed_count += len(points)
        except Exception:
            self.client.delete_collection(collection)
            raise
        return {"indexed": indexed_count, "truncated": truncated_count}

    def activate(self, *, collection: str, alias: str) -> None:
        existing = {
            item.alias_name
            for item in self.client.get_aliases().aliases
            if item.alias_name == alias
        }
        operations: list[models.CreateAliasOperation | models.DeleteAliasOperation] = []
        if alias in existing:
            operations.append(
                models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=collection,
                    alias_name=alias,
                )
            )
        )
        self.client.update_collection_aliases(operations)


class QdrantDenseRetriever:
    def __init__(
        self,
        *,
        client: QdrantClient,
        collection: str,
        encoder: DenseEncoder,
        repository: PostgresCorpusRepository,
        scope: RetrievalScope,
    ) -> None:
        self.client = client
        self.collection = collection
        self.encoder = encoder
        self.repository = repository
        self.scope = scope

    def search(self, query: str, *, filters: SearchFilters, limit: int) -> list[SearchHit]:
        encoded = self.encoder.encode_queries([query])
        candidate_limit = max(200, limit * 20)
        response = self.client.query_points(
            collection_name=self.collection,
            query=encoded.vectors[0],
            limit=candidate_limit,
            with_payload=True,
            with_vectors=False,
        )
        ordered_ids = [str(point.id) for point in response.points]
        records = self.repository.hydrate_chunks(ordered_ids, scope=self.scope)
        hits: list[SearchHit] = []
        for point in response.points:
            record = records.get(str(point.id))
            if record is None or not matches_filters(record, filters):
                continue
            score = float(point.score)
            hits.append(
                SearchHit(
                    record=record,
                    score=score,
                    rank=len(hits) + 1,
                    score_breakdown={"vector": score},
                )
            )
            if len(hits) == limit:
                break
        return hits
