from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from beken_retrieval.dense import EncodedBatch
from beken_retrieval.model_catalog import ModelSpec
from beken_retrieval.remote_inference import RemoteInferenceClient

from app.files.chunking import location_label
from app.files.vectors import PrivateFileVectorStore

# Candidates per ranker before fusion (and reranked after it), and passages kept.
# Reranking is the slow step on CPU, so the pool stays small; eight passages of
# ~1,400 characters stay well inside the file share of the context.
CANDIDATES = 12
RESULT_LIMIT = 8
RRF_K = 60


@dataclass(frozen=True)
class PrivateScope:
    """The files one chat may read: its own uploads and, inside a case, the case's."""

    workspace_id: UUID
    conversation_id: UUID
    case_id: UUID | None


@dataclass(frozen=True)
class PrivateHit:
    chunk_id: UUID
    file_id: UUID
    file_name: str
    chunk_index: int
    text: str
    section_title: str | None
    page_start: int | None
    page_end: int | None
    paragraph_start: int
    paragraph_end: int
    score: float

    @property
    def location_label(self) -> str:
        return location_label(
            self.page_start, self.page_end, self.paragraph_start, self.paragraph_end
        )


class QueryEncoder(Protocol):
    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch: ...


class PassageReranker(Protocol):
    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class RemotePassageReranker:
    def __init__(self, spec: ModelSpec, client: RemoteInferenceClient) -> None:
        self.spec = spec
        self.client = client

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return self.client.rerank(spec=self.spec, query=query, passages=passages)


class PrivateFileRetriever:
    """Hybrid search over one chat's ready files: dense + Turkish full text, fused, reranked."""

    def __init__(
        self,
        *,
        repository: Any,
        vectors: PrivateFileVectorStore,
        embedder: QueryEncoder,
        reranker: PassageReranker,
        candidates: int = CANDIDATES,
        limit: int = RESULT_LIMIT,
    ) -> None:
        self.repository = repository
        self.vectors = vectors
        self.embedder = embedder
        self.reranker = reranker
        self.candidates = candidates
        self.limit = limit

    async def search(self, query: str, scope: PrivateScope) -> list[PrivateHit]:
        # The database decides which files are readable right now (ready, same scope);
        # the vector filter then only admits those ids, so a lingering point is inert.
        file_ids = await self.repository.ready_file_ids(scope)
        if not file_ids:
            return []
        encoded = await asyncio.to_thread(self.embedder.encode_queries, [query])
        dense = await asyncio.to_thread(
            self.vectors.search,
            workspace_id=scope.workspace_id,
            file_ids=file_ids,
            vector=encoded.vectors[0],
            limit=self.candidates,
        )
        lexical = await self.repository.search_file_chunks(
            scope.workspace_id, file_ids, query, limit=self.candidates
        )
        fused = _reciprocal_rank_fusion([[chunk_id for chunk_id, _ in dense], lexical])
        if not fused:
            return []
        chunks = await self.repository.get_file_chunks(
            scope.workspace_id, file_ids, fused[: self.candidates]
        )
        candidates = [chunks[chunk_id] for chunk_id in fused if chunk_id in chunks]
        if not candidates:
            return []
        scores = await asyncio.to_thread(
            self.reranker.score, query, [row["text"] for row in candidates]
        )
        ranked = sorted(
            zip(candidates, scores, strict=True), key=lambda item: (-item[1], item[0]["id"])
        )
        return [hit_from_row(row, score) for row, score in ranked[: self.limit]]


def _reciprocal_rank_fusion(rankings: Sequence[Sequence[UUID]]) -> list[UUID]:
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], str(chunk_id)))


def hit_from_row(row: dict[str, Any], score: float) -> PrivateHit:
    return PrivateHit(
        chunk_id=row["id"],
        file_id=row["file_id"],
        file_name=row["original_name"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        section_title=row["section_title"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        paragraph_start=row["paragraph_start"],
        paragraph_end=row["paragraph_end"],
        score=float(score),
    )
