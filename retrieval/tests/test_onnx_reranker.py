from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from beken_retrieval.model_catalog import ModelCatalog, ModelSpec
from beken_retrieval.reranking import (
    CrossEncoderReranker,
    OnnxCrossEncoderReranker,
    create_reranker,
    local_artifact_path,
)

SCALE = 0.001


class FakeTokenizer:
    """Pair ids a test can predict: [1, len(query), one id per passage character]."""

    def __call__(self, queries, passages, *, padding, truncation, max_length, return_tensors):
        rows = [
            ([1, len(query)] + [ord(char) % 50 + 2 for char in passage])[:max_length]
            for query, passage in zip(queries, passages, strict=True)
        ]
        if not padding:
            return {"input_ids": rows, "attention_mask": [[1] * len(row) for row in rows]}
        width = max(len(row) for row in rows)
        ids = np.zeros((len(rows), width), dtype=np.int64)
        mask = np.zeros((len(rows), width), dtype=np.int64)
        for index, row in enumerate(rows):
            ids[index, : len(row)] = row
            mask[index, : len(row)] = 1
        return {"input_ids": ids, "attention_mask": mask}


class FakeSession:
    """logit = SCALE * sum of unmasked ids, like the tiny ONNX graph below."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    def get_inputs(self):
        return [SimpleNamespace(name="input_ids"), SimpleNamespace(name="attention_mask")]

    def get_outputs(self):
        return [SimpleNamespace(name="logits")]

    def run(self, names, feed):
        assert names == ["logits"]
        self.batches.append(feed["input_ids"].shape[0])
        logits = SCALE * (feed["input_ids"] * feed["attention_mask"]).sum(axis=1, keepdims=True)
        return [logits.astype(np.float32)]


def expected(query: str, passage: str, max_length: int = 512) -> float:
    ids = ([1, len(query)] + [ord(char) % 50 + 2 for char in passage])[:max_length]
    return 1.0 / (1.0 + math.exp(-SCALE * sum(ids)))


PASSAGES = ["a" * 5, "b" * 40, "c" * 12, "d" * 25, "e" * 3]


def test_scores_come_back_in_the_callers_order_across_length_sorted_batches() -> None:
    session = FakeSession()
    reranker = OnnxCrossEncoderReranker(
        tokenizer=FakeTokenizer(), session=session, max_tokens=512, model_key="m", batch_size=2
    )

    scores = reranker.score("fesih", PASSAGES)

    assert scores == pytest.approx([expected("fesih", passage) for passage in PASSAGES], rel=1e-6)
    assert session.batches == [2, 2, 1]
    assert reranker.score("fesih", []) == []


def test_long_pairs_are_truncated_to_the_model_limit() -> None:
    reranker = OnnxCrossEncoderReranker(
        tokenizer=FakeTokenizer(), session=FakeSession(), max_tokens=10, model_key="m"
    )
    [score] = reranker.score("q", ["x" * 100])
    assert score == pytest.approx(expected("q", "x" * 100, max_length=10))


def test_a_model_without_the_expected_io_is_refused() -> None:
    session = FakeSession()
    session.get_outputs = lambda: [SimpleNamespace(name="sentence_embedding")]
    with pytest.raises(RuntimeError, match="expected inputs and logits"):
        OnnxCrossEncoderReranker(
            tokenizer=FakeTokenizer(), session=session, max_tokens=512, model_key="m"
        )


def spec(**overrides) -> ModelSpec:
    values = {
        "key": "bge-reranker-v2-m3",
        "model_id": "BAAI/bge-reranker-v2-m3",
        "revision": "0" * 40,
        "backend": "onnx",
        "safe_artifact": "bge-reranker-v2-m3/int8/model.onnx",
        "max_tokens": 512,
        "artifact_sha256": "a" * 64,
    }
    return ModelSpec(**{**values, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"safe_artifact": "../outside/model.onnx"},
        {"safe_artifact": "/etc/model.onnx"},
        {"safe_artifact": "bge-reranker-v2-m3/int8/model.pkl"},
        {"artifact_sha256": None},
        {"artifact_sha256": "not-a-hash"},
        {"backend": "torch"},
    ],
)
def test_only_pinned_onnx_files_inside_the_artifact_directory_are_accepted(
    tmp_path, overrides
) -> None:
    with pytest.raises(ValueError, match="pinned local .onnx artifact"):
        local_artifact_path(spec(**overrides), tmp_path)


def test_a_file_whose_bytes_changed_is_not_loaded(tmp_path) -> None:
    path = tmp_path / "bge-reranker-v2-m3" / "int8" / "model.onnx"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="does not match its pinned hash"):
        OnnxCrossEncoderReranker.from_spec(spec(), tmp_path)


def test_unknown_backends_are_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unsupported safe model backend"):
        create_reranker(spec(backend="pickle"), artifact_dir=tmp_path)


def test_the_catalog_pins_the_reranker_to_a_hashed_local_onnx_file(tmp_path) -> None:
    catalog = ModelCatalog.load(Path("retrieval/config/models.json"))
    pinned = catalog.get("bge-reranker-v2-m3")
    assert pinned.backend == "onnx" and pinned.max_tokens == 512
    assert re.fullmatch(r"[0-9a-f]{64}", pinned.artifact_sha256 or "")
    assert local_artifact_path(pinned, tmp_path) == tmp_path / Path(pinned.safe_artifact)
    # The artifact is derived from the same pinned Hub revision the tokenizer uses.
    assert len(pinned.revision) == 40


def test_a_real_onnx_graph_scores_like_the_fake(tmp_path, monkeypatch) -> None:
    onnx = pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    import transformers
    from onnx import TensorProto, helper

    graph = helper.make_graph(
        [
            helper.make_node("Mul", ["input_ids", "attention_mask"], ["kept"]),
            helper.make_node("Cast", ["kept"], ["kept_float"], to=TensorProto.FLOAT),
            helper.make_node("ReduceSum", ["kept_float", "axes"], ["total"], keepdims=1),
            helper.make_node("Mul", ["total", "scale"], ["logits"]),
        ],
        "tiny-reranker",
        [
            helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["batch", "sequence"]),
            helper.make_tensor_value_info(
                "attention_mask", TensorProto.INT64, ["batch", "sequence"]
            ),
        ],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["batch", 1])],
        initializer=[
            helper.make_tensor("axes", TensorProto.INT64, [1], [1]),
            helper.make_tensor("scale", TensorProto.FLOAT, [], [SCALE]),
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    path = tmp_path / "bge-reranker-v2-m3" / "int8" / "model.onnx"
    path.parent.mkdir(parents=True)
    onnx.save(model, str(path))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    requested: list[dict] = []

    def from_pretrained(model_id, **kwargs):
        requested.append({"model_id": model_id, **kwargs})
        return FakeTokenizer()

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", from_pretrained)

    reranker = create_reranker(spec(artifact_sha256=digest), artifact_dir=tmp_path)

    scores = reranker.score("fesih", PASSAGES)
    assert scores == pytest.approx([expected("fesih", passage) for passage in PASSAGES], rel=1e-5)
    # The tokenizer comes from the pinned Hub revision, never with cached credentials.
    assert requested == [
        {
            "model_id": "BAAI/bge-reranker-v2-m3",
            "revision": "0" * 40,
            "trust_remote_code": False,
            "token": False,
        }
    ]
    assert json.dumps(scores)  # plain floats, serialisable by the model service


def test_the_torch_path_stays_available_for_evaluation(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=lambda *_, **__: None)
    )
    torch_spec = replace(spec(), backend="torch", safe_artifact="model.safetensors")
    reranker = create_reranker(torch_spec, artifact_dir=Path("/nonexistent"))
    assert isinstance(reranker, CrossEncoderReranker)
