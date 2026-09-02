from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from beken_retrieval.context import build_embedding_context
from beken_retrieval.model_catalog import ModelSpec
from beken_retrieval.model_loading import safe_model_loading
from beken_retrieval.models import ChunkRecord


@dataclass(frozen=True)
class EncodedBatch:
    vectors: list[list[float]]
    truncated: tuple[bool, ...]


class DenseEncoder(Protocol):
    dimensions: int
    model_key: str

    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch: ...

    def encode_records(self, records: Sequence[ChunkRecord]) -> EncodedBatch: ...


class DeterministicFakeEncoder:
    """Small deterministic encoder for CI; never used for production quality claims."""

    def __init__(self, dimensions: int = 16, model_key: str = "fake-ci") -> None:
        self.dimensions = dimensions
        self.model_key = model_key

    def _encode(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        values = [
            ((digest[index % len(digest)] / 255.0) * 2) - 1 for index in range(self.dimensions)
        ]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch:
        return EncodedBatch(
            vectors=[self._encode(text) for text in texts],
            truncated=tuple(False for _ in texts),
        )

    def encode_records(self, records: Sequence[ChunkRecord]) -> EncodedBatch:
        return self.encode_queries([build_embedding_context(record).text for record in records])


class SentenceTransformerDenseEncoder:
    def __init__(self, spec: ModelSpec) -> None:
        if spec.dimensions is None or spec.max_tokens is None:
            raise ValueError(f"Dense model {spec.key!r} lacks dimensions/max_tokens")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Install beken-retrieval[models] to use transformer encoders"
            ) from exc
        kwargs: dict = {
            "revision": spec.revision,
            "trust_remote_code": False,
            "token": False,  # Public catalog: never inherit a developer's cached credentials.
        }
        if spec.backend == "torch":
            if not spec.safe_artifact.endswith(".safetensors"):
                raise ValueError("Torch model must be pinned to a safetensors artifact")
            kwargs["model_kwargs"] = {"use_safetensors": True}
        else:
            raise ValueError("SentenceTransformerDenseEncoder requires a torch model")
        with safe_model_loading():
            self.model = SentenceTransformer(spec.model_id, **kwargs)
        self.model.max_seq_length = spec.max_tokens
        self.spec = spec
        self.dimensions = spec.dimensions
        self.model_key = spec.key

    def _encode(self, texts: Sequence[str], prefix: str) -> EncodedBatch:
        prefixed = [prefix + text for text in texts]
        truncated = tuple(
            len(self.model.tokenizer(text, truncation=False)["input_ids"])
            > int(self.spec.max_tokens or 0)
            for text in prefixed
        )
        vectors = self.model.encode(
            prefixed,
            batch_size=8,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return EncodedBatch(vectors=vectors.tolist(), truncated=truncated)

    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch:
        return self._encode(texts, self.spec.query_prefix)

    def encode_records(self, records: Sequence[ChunkRecord]) -> EncodedBatch:
        contexts = [build_embedding_context(record).text for record in records]
        return self._encode(contexts, self.spec.passage_prefix)


class OnnxDenseEncoder:
    def __init__(self, spec: ModelSpec) -> None:
        if (
            spec.backend != "onnx"
            or not spec.safe_artifact.endswith(".onnx")
            or spec.dimensions is None
            or spec.max_tokens is None
        ):
            raise ValueError("ONNX dense model metadata is incomplete or unsafe")
        try:
            import onnxruntime
            from huggingface_hub import hf_hub_download
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("Install beken-retrieval[models] to use ONNX encoders") from exc
        with safe_model_loading():
            model_path = hf_hub_download(
                spec.model_id,
                spec.safe_artifact,
                revision=spec.revision,
                token=False,
            )
            for artifact in spec.supporting_artifacts:
                if (
                    not artifact.startswith("onnx/")
                    or ".." in artifact.split("/")
                    or not artifact.endswith(".onnx_data")
                ):
                    raise ValueError("Unsafe ONNX supporting artifact")
                hf_hub_download(
                    spec.model_id,
                    artifact,
                    revision=spec.revision,
                    token=False,
                )
            self.tokenizer = AutoTokenizer.from_pretrained(
                spec.model_id,
                revision=spec.revision,
                trust_remote_code=False,
                token=False,
            )
            self.session = onnxruntime.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"],
            )
        output_names = {output.name for output in self.session.get_outputs()}
        if "sentence_embedding" not in output_names:
            raise RuntimeError("Pinned ONNX model lacks sentence_embedding output")
        self.spec = spec
        self.dimensions = spec.dimensions
        self.model_key = spec.key

    def _encode(self, texts: Sequence[str], prefix: str) -> EncodedBatch:
        import numpy as np

        prefixed = [prefix + text for text in texts]
        truncated = tuple(
            len(self.tokenizer(text, truncation=False)["input_ids"])
            > int(self.spec.max_tokens or 0)
            for text in prefixed
        )
        inputs = self.tokenizer(
            prefixed,
            padding=True,
            truncation=True,
            max_length=self.spec.max_tokens,
            return_tensors="np",
        )
        feed = {
            input_.name: np.asarray(inputs[input_.name], dtype=np.int64)
            for input_ in self.session.get_inputs()
        }
        vectors = self.session.run(["sentence_embedding"], feed)[0]
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-12)
        return EncodedBatch(vectors=vectors.tolist(), truncated=truncated)

    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch:
        return self._encode(texts, self.spec.query_prefix)

    def encode_records(self, records: Sequence[ChunkRecord]) -> EncodedBatch:
        contexts = [build_embedding_context(record).text for record in records]
        return self._encode(contexts, self.spec.passage_prefix)


def create_dense_encoder(spec: ModelSpec) -> DenseEncoder:
    if spec.backend == "torch":
        return SentenceTransformerDenseEncoder(spec)
    if spec.backend == "onnx":
        return OnnxDenseEncoder(spec)
    raise ValueError(f"Unsupported safe model backend: {spec.backend}")
