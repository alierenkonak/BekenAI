from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import numpy as np

from beken_retrieval.model_catalog import ModelSpec
from beken_retrieval.model_loading import safe_model_loading
from beken_retrieval.models import SearchHit

RERANK_BATCH_SIZE = 8


class PassageScorer(Protocol):
    model_key: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...

    def rerank(self, query: str, hits: list[SearchHit], *, limit: int) -> list[SearchHit]: ...


class IdentityReranker:
    def rerank(self, query: str, hits: list[SearchHit], *, limit: int) -> list[SearchHit]:
        return [hit.with_rank(rank) for rank, hit in enumerate(hits[:limit], start=1)]


def _rerank(
    scorer: PassageScorer, query: str, hits: list[SearchHit], limit: int
) -> list[SearchHit]:
    if not hits:
        return []
    scores = scorer.score(query, [hit.record.text for hit in hits])
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
            batch_size=RERANK_BATCH_SIZE,
            show_progress_bar=False,
        )
        return np.asarray(scores).reshape(-1).astype(float).tolist()

    def rerank(self, query: str, hits: list[SearchHit], *, limit: int) -> list[SearchHit]:
        return _rerank(self, query, hits, limit)


class OnnxCrossEncoderReranker:
    """The pinned cross-encoder, exported to ONNX (and quantized) by `export-reranker-onnx`.

    The converted file is ours rather than the Hub's, so it lives in the model service's
    artifact directory and must match the SHA-256 pinned in the catalog. The tokenizer
    still comes from the pinned Hub revision the export started from.
    """

    def __init__(
        self,
        *,
        tokenizer: Any,
        session: Any,
        max_tokens: int,
        model_key: str,
        batch_size: int = RERANK_BATCH_SIZE,
    ) -> None:
        inputs = {item.name for item in session.get_inputs()}
        outputs = {item.name for item in session.get_outputs()}
        if inputs != {"input_ids", "attention_mask"} or "logits" not in outputs:
            raise RuntimeError("ONNX reranker does not expose the expected inputs and logits")
        self.tokenizer = tokenizer
        self.session = session
        self.max_tokens = max_tokens
        self.model_key = model_key
        self.batch_size = batch_size

    @classmethod
    def from_spec(
        cls, spec: ModelSpec, artifact_dir: Path, *, threads: int = 0
    ) -> OnnxCrossEncoderReranker:
        path = local_artifact_path(spec, artifact_dir)
        if spec.max_tokens is None:
            raise ValueError("ONNX reranker metadata is incomplete")
        if file_sha256(path) != spec.artifact_sha256:
            raise ValueError("ONNX reranker artifact does not match its pinned hash")
        try:
            import onnxruntime
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("Install beken-retrieval[models] to use the ONNX reranker") from exc
        with safe_model_loading():
            tokenizer = AutoTokenizer.from_pretrained(
                spec.model_id,
                revision=spec.revision,
                trust_remote_code=False,
                token=False,
            )
        options = onnxruntime.SessionOptions()
        # 0 lets ONNX Runtime use one thread per physical core.
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = onnxruntime.InferenceSession(
            str(path), options, providers=["CPUExecutionProvider"]
        )
        return cls(
            tokenizer=tokenizer, session=session, max_tokens=spec.max_tokens, model_key=spec.key
        )

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        # A batch costs as much as its longest pair, so similar lengths are batched
        # together; scores are returned in the caller's order.
        unpadded = self._encode([query] * len(passages), list(passages), padding=False)
        lengths = [len(ids) for ids in unpadded["input_ids"]]
        order = sorted(range(len(passages)), key=lambda index: (-lengths[index], index))
        logits = np.empty(len(passages), dtype=np.float64)
        for start in range(0, len(order), self.batch_size):
            batch = order[start : start + self.batch_size]
            encoded = self._encode([query] * len(batch), [passages[index] for index in batch])
            output = self.session.run(
                ["logits"],
                {
                    "input_ids": np.asarray(encoded["input_ids"], dtype=np.int64),
                    "attention_mask": np.asarray(encoded["attention_mask"], dtype=np.int64),
                },
            )[0]
            logits[batch] = np.asarray(output, dtype=np.float64).reshape(-1)
        # The same sigmoid the PyTorch cross-encoder applies to a single-label model.
        return (1.0 / (1.0 + np.exp(-logits))).tolist()

    def _encode(self, queries: list[str], passages: list[str], *, padding: bool = True):
        return self.tokenizer(
            queries,
            passages,
            padding=padding,
            truncation=True,
            max_length=self.max_tokens,
            return_tensors="np" if padding else None,
        )

    def rerank(self, query: str, hits: list[SearchHit], *, limit: int) -> list[SearchHit]:
        return _rerank(self, query, hits, limit)


def local_artifact_path(spec: ModelSpec, artifact_dir: Path) -> Path:
    """Resolve a converted artifact inside the artifact directory, never outside it."""
    relative = PurePosixPath(spec.safe_artifact)
    if (
        spec.backend != "onnx"
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.suffix != ".onnx"
        or not re.fullmatch(r"[0-9a-f]{64}", spec.artifact_sha256 or "")
    ):
        raise ValueError("ONNX reranker must name a pinned local .onnx artifact")
    return artifact_dir.joinpath(*relative.parts)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def create_reranker(spec: ModelSpec, *, artifact_dir: Path) -> PassageScorer:
    if spec.backend == "torch":
        return CrossEncoderReranker(spec)
    if spec.backend == "onnx":
        return OnnxCrossEncoderReranker.from_spec(spec, artifact_dir)
    raise ValueError(f"Unsupported safe model backend: {spec.backend}")
