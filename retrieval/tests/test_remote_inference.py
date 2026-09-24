from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from beken_retrieval.config import RetrievalSettings
from beken_retrieval.model_catalog import ModelCatalog
from beken_retrieval.remote_inference import (
    RemoteDenseEncoder,
    RemoteInferenceClient,
    TransientInferenceError,
)


def _client(handler) -> RemoteInferenceClient:
    return RemoteInferenceClient(
        base_url="http://127.0.0.1:8081",
        token="t" * 32,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def test_remote_dense_encoder_validates_pinned_model_response() -> None:
    spec = ModelCatalog.load(RetrievalSettings().retrieval_model_catalog).get("bge-m3")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {'t' * 32}"
        return httpx.Response(
            200,
            json={
                "model_key": spec.key,
                "model_revision": spec.revision,
                "dimensions": spec.dimensions,
                "vectors": [[0.0] * int(spec.dimensions or 0)],
                "truncated": [False],
            },
        )

    encoded = RemoteDenseEncoder(spec, _client(handler)).encode_queries(["işe iade"])
    assert len(encoded.vectors[0]) == 1024
    assert encoded.truncated == (False,)


def test_remote_client_rejects_redirects_without_leaking_provider_details() -> None:
    spec = ModelCatalog.load(RetrievalSettings().retrieval_model_catalog).get("bge-m3")
    client = _client(lambda _: httpx.Response(307, headers={"location": "https://example.com"}))

    with pytest.raises(RuntimeError, match="Remote model inference failed") as caught:
        client.embed(spec=spec, texts=["iş sözleşmesi"], input_type="query")

    assert "example.com" not in str(caught.value)


@pytest.mark.parametrize("status_code", [429, 503])
def test_remote_client_marks_capacity_and_service_errors_retryable(status_code: int) -> None:
    spec = ModelCatalog.load(RetrievalSettings().retrieval_model_catalog).get("bge-m3")
    client = _client(lambda _: httpx.Response(status_code, text="private provider detail"))

    with pytest.raises(TransientInferenceError) as caught:
        client.embed(spec=spec, texts=["işe iade"], input_type="query")

    assert "private provider detail" not in str(caught.value)


def test_remote_client_does_not_retry_invalid_request() -> None:
    spec = ModelCatalog.load(RetrievalSettings().retrieval_model_catalog).get("bge-m3")
    client = _client(lambda _: httpx.Response(422, text="private provider detail"))

    with pytest.raises(RuntimeError, match="Remote model inference failed") as caught:
        client.embed(spec=spec, texts=["işe iade"], input_type="query")

    assert not isinstance(caught.value, TransientInferenceError)
    assert "private provider detail" not in str(caught.value)


def test_remote_client_marks_transport_errors_retryable() -> None:
    spec = ModelCatalog.load(RetrievalSettings().retrieval_model_catalog).get("bge-m3")

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private transport detail", request=request)

    with pytest.raises(TransientInferenceError) as caught:
        _client(unavailable).embed(spec=spec, texts=["işe iade"], input_type="query")

    assert "private transport detail" not in str(caught.value)


def test_plain_http_model_service_is_restricted_to_loopback() -> None:
    external = RetrievalSettings(
        model_inference_url="http://example.com",
        model_inference_token=SecretStr("t" * 32),
    )
    with pytest.raises(ValueError, match="loopback"):
        _ = external.model_inference_base_url

    loopback = RetrievalSettings(
        model_inference_url="http://127.0.0.1:8081",
        model_inference_token=SecretStr("t" * 32),
    )
    assert loopback.model_inference_base_url == "http://127.0.0.1:8081"
    assert loopback.model_inference_secret == "t" * 32
