from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from beken_retrieval.model_service import (
    EmbeddingRequest,
    EmbeddingResponse,
    ModelServiceSettings,
    RerankRequest,
    RerankResponse,
    create_app,
)


class FakeRuntime:
    loaded = False

    def load(self) -> None:
        self.loaded = True

    def ready(self) -> bool:
        return self.loaded

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            model_key=request.model_key,
            model_revision="a" * 40,
            dimensions=3,
            vectors=[[1.0, 0.0, 0.0] for _ in request.texts],
            truncated=[False for _ in request.texts],
        )

    def rerank(self, request: RerankRequest) -> RerankResponse:
        return RerankResponse(
            model_key=request.model_key,
            model_revision="b" * 40,
            scores=[float(index) for index, _ in enumerate(request.passages)],
        )


def test_model_service_requires_bearer_token_and_serves_pinned_endpoints() -> None:
    token = "s" * 32
    settings = ModelServiceSettings(
        model_service_token=SecretStr(token),
        model_catalog_path=Path("unused-in-fake-runtime.json"),
    )
    app = create_app(settings=settings, runtime=FakeRuntime())

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").json() == {"status": "ready"}
        assert client.post(
            "/v1/embeddings",
            json={"model_key": "bge-m3", "input_type": "query", "texts": ["kıdem"]},
        ).status_code == 401

        headers = {"Authorization": f"Bearer {token}"}
        embedding = client.post(
            "/v1/embeddings",
            headers=headers,
            json={"model_key": "bge-m3", "input_type": "query", "texts": ["kıdem"]},
        )
        assert embedding.status_code == 200
        assert embedding.json()["vectors"] == [[1.0, 0.0, 0.0]]

        reranked = client.post(
            "/v1/rerank",
            headers=headers,
            json={
                "model_key": "bge-reranker-v2-m3",
                "query": "İhbar süresi nedir?",
                "passages": ["Birinci pasaj", "İkinci pasaj"],
            },
        )
        assert reranked.status_code == 200
        assert reranked.json()["scores"] == [0.0, 1.0]


def test_model_service_rejects_unknown_models_and_oversized_batches() -> None:
    token = "s" * 32
    app = create_app(
        settings=ModelServiceSettings(
            model_service_token=SecretStr(token),
            model_catalog_path=Path("unused-in-fake-runtime.json"),
        ),
        runtime=FakeRuntime(),
    )
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        unknown = client.post(
            "/v1/embeddings",
            headers=headers,
            json={"model_key": "untrusted-model", "input_type": "query", "texts": ["test"]},
        )
        assert unknown.status_code == 422

        oversized = client.post(
            "/v1/embeddings",
            headers=headers,
            json={"model_key": "bge-m3", "input_type": "query", "texts": ["x"] * 33},
        )
        assert oversized.status_code == 422
