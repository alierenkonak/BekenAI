from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from beken_retrieval import cli
from beken_retrieval.dense import OnnxDenseEncoder, SentenceTransformerDenseEncoder
from beken_retrieval.model_catalog import ModelCatalog
from beken_retrieval.model_loading import safe_model_loading
from beken_retrieval.reranking import CrossEncoderReranker


@pytest.fixture
def provider_stubs(monkeypatch):
    calls = []
    state = {"fail_at": None}

    def call(stage, kwargs):
        calls.append((stage, kwargs))
        if stage == state["fail_at"]:
            logging.getLogger("huggingface_hub.utils._http").warning(
                "Authorization: Bearer TEST_ONLY_SECRET_SENTINEL "
                "https://example.invalid/?token=TEST_ONLY_SECRET_SENTINEL"
            )
            raise ConnectionError(
                "Authorization: Bearer TEST_ONLY_SECRET_SENTINEL "
                "https://example.invalid/?token=TEST_ONLY_SECRET_SENTINEL"
            )

    def torch_model(*args, **kwargs):
        call("dense", kwargs)
        return SimpleNamespace()

    def reranker(*args, **kwargs):
        call("reranker", kwargs)
        return SimpleNamespace()

    def download(*args, **kwargs):
        call("download", kwargs)
        return "fixture.onnx"

    def tokenizer(*args, **kwargs):
        call("tokenizer", kwargs)
        return SimpleNamespace()

    def session(*args, **kwargs):
        call("session", kwargs)
        return SimpleNamespace(get_outputs=lambda: [SimpleNamespace(name="sentence_embedding")])

    monkeypatch.setenv("HF_TOKEN", "TEST_ONLY_CACHED_TOKEN")
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(
        SentenceTransformer=torch_model, CrossEncoder=reranker,
    ))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=tokenizer),
    ))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=session))
    return calls, state


def load(kind):
    catalog = ModelCatalog.load(Path("retrieval/config/models.json"))
    if kind == "dense":
        return SentenceTransformerDenseEncoder(catalog.get("multilingual-e5-base"))
    if kind == "reranker":
        # Production serves an ONNX export; the PyTorch loader stays for evaluation.
        torch_spec = replace(
            catalog.get("bge-reranker-v2-m3"),
            backend="torch",
            safe_artifact="model.safetensors",
            artifact_sha256=None,
        )
        return CrossEncoderReranker(torch_spec)
    return OnnxDenseEncoder(catalog.get("bge-m3"))


def test_all_public_model_loaders_disable_implicit_credentials(provider_stubs):
    calls, _ = provider_stubs
    dense = load("dense")
    onnx = load("onnx")
    reranker = load("reranker")
    assert dense.dimensions == 768
    assert onnx.dimensions == 1024
    assert reranker.model_key == "bge-reranker-v2-m3"
    remote_calls = [(stage, kwargs) for stage, kwargs in calls if stage != "session"]
    assert {stage for stage, _ in remote_calls} == {"dense", "download", "tokenizer", "reranker"}
    for _, kwargs in remote_calls:
        assert kwargs["token"] is False
        assert len(kwargs["revision"]) == 40
    assert dict(calls)["dense"]["model_kwargs"]["use_safetensors"] is True
    assert dict(calls)["reranker"]["model_kwargs"]["use_safetensors"] is True
    assert dict(calls)["reranker"]["max_length"] == 512
    assert sum(stage == "download" for stage, _ in calls) == 2


def test_onnx_loader_rejects_unlisted_supporting_artifact(provider_stubs):
    catalog = ModelCatalog.load(Path("retrieval/config/models.json"))
    spec = catalog.get("bge-m3")
    unsafe = spec.__class__(
        **{**spec.__dict__, "supporting_artifacts": ("../model.pkl",)}
    )

    with pytest.raises(RuntimeError, match="Pinned public model could not be loaded"):
        OnnxDenseEncoder(unsafe)


@pytest.mark.parametrize("stage", ["dense", "reranker", "download", "tokenizer", "session"])
def test_loader_tracebacks_do_not_include_provider_secrets(provider_stubs, stage, capsys, caplog):
    _, state = provider_stubs
    state["fail_at"] = stage
    with pytest.raises(RuntimeError, match="Pinned public model could not be loaded") as caught:
        load(stage if stage in {"dense", "reranker"} else "onnx")
    formatted = "".join(traceback.format_exception(caught.value))
    captured = capsys.readouterr()
    assert "TEST_ONLY_SECRET_SENTINEL" not in formatted + caplog.text + captured.out + captured.err
    assert caught.value.__suppress_context__
    assert "Model download transport event" in caplog.text


@pytest.mark.parametrize("error_type", [RuntimeError, ConnectionError, ValueError])
def test_cli_does_not_print_raw_provider_errors(monkeypatch, capsys, error_type):
    def fail(*args):
        raise error_type("Authorization: Bearer TEST_ONLY_SECRET_SENTINEL")

    args = SimpleNamespace(handler=fail)
    monkeypatch.setattr(cli, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(cli, "get_settings", lambda: None)
    assert cli.main() == 2
    captured = capsys.readouterr()
    assert "TEST_ONLY_SECRET_SENTINEL" not in captured.out + captured.err
    assert error_type.__name__ in captured.out


def test_transport_logs_keep_safe_status_and_retry_information(caplog):
    logger = logging.getLogger("huggingface_hub.utils._http")
    with safe_model_loading():
        logger.warning(
            "HTTP Error 503 thrown while requesting GET "
            "https://example.invalid/?signature=TEST_ONLY_SECRET_SENTINEL"
        )
        logger.warning("Retrying in 2s [Retry 1/5].")
        try:
            raise ConnectionError("TEST_ONLY_SECRET_SENTINEL")
        except ConnectionError:
            logger.exception("Download failed")
    assert "HTTP error 503" in caplog.text
    assert "Retrying in 2s [Retry 1/5]." in caplog.text
    assert "TEST_ONLY_SECRET_SENTINEL" not in caplog.text
    assert [record.levelname for record in caplog.records] == ["WARNING", "WARNING", "ERROR"]
