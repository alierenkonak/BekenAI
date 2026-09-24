from __future__ import annotations

from collections.abc import Sequence

import httpx
from pydantic import BaseModel, ConfigDict

from beken_retrieval.context import build_embedding_context
from beken_retrieval.dense import EncodedBatch
from beken_retrieval.model_catalog import ModelSpec
from beken_retrieval.models import ChunkRecord, SearchHit


class _EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: str
    model_revision: str
    dimensions: int
    vectors: list[list[float]]
    truncated: list[bool]


class _RerankResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: str
    model_revision: str
    scores: list[float]


class TransientInferenceError(RuntimeError):
    """A retryable transport, rate-limit, or model-service failure."""


class RemoteInferenceClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "beken-retrieval/0.1",
            },
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = self.client.post(path, json=payload)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("Response body must be an object")
            return value
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 or exc.response.status_code >= 500:
                raise TransientInferenceError(
                    "Remote model inference temporarily unavailable"
                ) from None
            raise RuntimeError("Remote model inference failed (HTTPStatusError)") from None
        except httpx.TransportError:
            raise TransientInferenceError(
                "Remote model inference temporarily unavailable"
            ) from None
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(
                f"Remote model inference failed ({type(exc).__name__})"
            ) from None

    def embed(
        self,
        *,
        spec: ModelSpec,
        texts: Sequence[str],
        input_type: str,
    ) -> EncodedBatch:
        payload = {
            "model_key": spec.key,
            "input_type": input_type,
            "texts": list(texts),
        }
        try:
            parsed = _EmbeddingResponse.model_validate(self._post("/v1/embeddings", payload))
        except ValueError:
            raise RuntimeError("Remote embedding response validation failed") from None
        if (
            parsed.model_key != spec.key
            or parsed.model_revision != spec.revision
            or parsed.dimensions != spec.dimensions
            or len(parsed.vectors) != len(texts)
            or len(parsed.truncated) != len(texts)
            or any(len(vector) != spec.dimensions for vector in parsed.vectors)
        ):
            raise RuntimeError("Remote embedding response does not match the pinned model")
        return EncodedBatch(vectors=parsed.vectors, truncated=tuple(parsed.truncated))

    def rerank(
        self,
        *,
        spec: ModelSpec,
        query: str,
        passages: Sequence[str],
    ) -> list[float]:
        payload = {
            "model_key": spec.key,
            "query": query,
            "passages": list(passages),
        }
        try:
            parsed = _RerankResponse.model_validate(self._post("/v1/rerank", payload))
        except ValueError:
            raise RuntimeError("Remote reranker response validation failed") from None
        if (
            parsed.model_key != spec.key
            or parsed.model_revision != spec.revision
            or len(parsed.scores) != len(passages)
        ):
            raise RuntimeError("Remote reranker response does not match the pinned model")
        return parsed.scores


class RemoteDenseEncoder:
    def __init__(self, spec: ModelSpec, client: RemoteInferenceClient) -> None:
        if spec.dimensions is None or spec.max_tokens is None:
            raise ValueError("Remote dense model metadata is incomplete")
        self.spec = spec
        self.client = client
        self.dimensions = spec.dimensions
        self.model_key = spec.key

    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch:
        return self.client.embed(spec=self.spec, texts=texts, input_type="query")

    def encode_records(self, records: Sequence[ChunkRecord]) -> EncodedBatch:
        contexts = [build_embedding_context(record).text for record in records]
        return self.client.embed(spec=self.spec, texts=contexts, input_type="passage")


class RemoteReranker:
    def __init__(self, spec: ModelSpec, client: RemoteInferenceClient) -> None:
        self.spec = spec
        self.client = client
        self.model_key = spec.key

    def rerank(self, query: str, hits: list[SearchHit], *, limit: int) -> list[SearchHit]:
        if not hits:
            return []
        scores = self.client.rerank(
            spec=self.spec,
            query=query,
            passages=[hit.record.text for hit in hits],
        )
        rescored = [
            SearchHit(
                record=hit.record,
                score=float(score),
                score_breakdown={**hit.score_breakdown, "reranker": float(score)},
            )
            for hit, score in zip(hits, scores, strict=True)
        ]
        rescored.sort(key=lambda hit: (-hit.score, hit.record.chunk_id))
        return [hit.with_rank(rank) for rank, hit in enumerate(rescored[:limit], start=1)]
