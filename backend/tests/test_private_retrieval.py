from __future__ import annotations

from uuid import uuid4

import pytest
from beken_retrieval.dense import EncodedBatch

from app.files.retrieval import PrivateFileRetriever, PrivateScope, _reciprocal_rank_fusion

SCOPE = PrivateScope(workspace_id=uuid4(), conversation_id=uuid4(), case_id=None)


def _row(chunk_id, file_id, text):
    return {
        "id": chunk_id,
        "file_id": file_id,
        "chunk_index": 0,
        "text": text,
        "section_title": None,
        "page_start": 1,
        "page_end": 1,
        "paragraph_start": 1,
        "paragraph_end": 1,
        "original_name": "Dilekçe.pdf",
    }


class FakeRepository:
    def __init__(self, ready: list, rows: dict, lexical: list) -> None:
        self.ready = ready
        self.rows = rows
        self.lexical = lexical
        self.chunk_requests: list = []

    async def ready_file_ids(self, scope):
        assert scope is SCOPE
        return self.ready

    async def search_file_chunks(self, workspace_id, file_ids, query, *, limit):
        assert workspace_id == SCOPE.workspace_id and file_ids == self.ready
        return self.lexical

    async def get_file_chunks(self, workspace_id, file_ids, chunk_ids):
        self.chunk_requests.append(list(chunk_ids))
        return {chunk_id: self.rows[chunk_id] for chunk_id in chunk_ids if chunk_id in self.rows}


class FakeVectors:
    def __init__(self, dense: list) -> None:
        self.dense = dense
        self.calls: list[dict] = []

    def search(self, **values):
        self.calls.append(values)
        return self.dense


class FakeEncoder:
    def __init__(self) -> None:
        self.calls = 0

    def encode_queries(self, texts):
        self.calls += 1
        return EncodedBatch(vectors=[[0.1, 0.2]], truncated=(False,))


class FakeReranker:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def score(self, query, passages):
        return [self.scores[passage] for passage in passages]


@pytest.mark.asyncio
async def test_no_ready_files_means_no_model_or_vector_calls() -> None:
    encoder, vectors = FakeEncoder(), FakeVectors([])
    retriever = PrivateFileRetriever(
        repository=FakeRepository([], {}, []),
        vectors=vectors,
        embedder=encoder,
        reranker=FakeReranker({}),
    )

    assert await retriever.search("fesih gerekçesi", SCOPE) == []
    assert encoder.calls == 0 and vectors.calls == []


@pytest.mark.asyncio
async def test_hybrid_candidates_are_fused_reranked_and_limited() -> None:
    file_id = uuid4()
    ids = [uuid4() for _ in range(4)]
    texts = ["gerekçe performans", "savunma alınmadı", "bordro", "tanık"]
    rows = {
        chunk_id: _row(chunk_id, file_id, text)
        for chunk_id, text in zip(ids, texts, strict=True)
    }
    vectors = FakeVectors([(ids[0], 0.9), (ids[1], 0.8), (ids[2], 0.1)])
    retriever = PrivateFileRetriever(
        repository=FakeRepository([file_id], rows, [ids[3], ids[1]]),
        vectors=vectors,
        embedder=FakeEncoder(),
        reranker=FakeReranker(dict(zip(texts, [0.2, 0.95, 0.1, 0.5], strict=True))),
        limit=2,
    )

    hits = await retriever.search("savunma alınmadan fesih", SCOPE)

    assert [hit.text for hit in hits] == ["savunma alınmadı", "tanık"]
    assert hits[0].file_name == "Dilekçe.pdf" and hits[0].location_label == "s. 1"
    # The vector store only ever sees this workspace and its ready files.
    assert vectors.calls[0]["workspace_id"] == SCOPE.workspace_id
    assert vectors.calls[0]["file_ids"] == [file_id]


def test_rrf_rewards_agreement_between_rankers() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()

    assert _reciprocal_rank_fusion([[a, b], [b, c]])[0] == b
