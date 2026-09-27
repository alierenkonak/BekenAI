from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from beken_retrieval.model_catalog import ModelSpec
from beken_retrieval.model_loading import safe_model_loading
from beken_retrieval.models import SearchHit


class IdentityReranker:
    def rerank(self, query: str, hits: list[SearchHit], *, limit: int) -> list[SearchHit]:
        return [hit.with_rank(rank) for rank, hit in enumerate(hits[:limit], start=1)]


class CrossEncoderReranker:
    def __init__(self, spec: ModelSpec) -> None:
        if spec.backend != "torch" or not spec.safe_artifact.endswith(".safetensors"):
            raise ValueError("Cross-encoder must use a pinned safetensors artifact")
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("Install beken-retrieval[models] to use the reranker") from exc
        with safe_model_loading():
            self.model = CrossEncoder(
                spec.model_id,
                revision=spec.revision,
                trust_remote_code=False,
                token=False,
                model_kwargs={"use_safetensors": True},
                # Without a cap the tokenizer allows 8,192 tokens, and on CPU a batch
                # costs as much as its longest passage.
                max_length=spec.max_tokens,
            )
        self.model_key = spec.key

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        scores = self.model.predict(
            [(query, passage) for passage in passages],
            batch_size=8,
            show_progress_bar=False,
        )
        return np.asarray(scores).reshape(-1).astype(float).tolist()

    def rerank(self, query: str, hits: list[SearchHit], *, limit: int) -> list[SearchHit]:
        if not hits:
            return []
        scores = self.score(query, [hit.record.text for hit in hits])
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
