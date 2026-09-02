import asyncio
import logging
import secrets
import threading
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from beken_retrieval.dense import DenseEncoder, create_dense_encoder
from beken_retrieval.model_catalog import ModelCatalog
from beken_retrieval.reranking import CrossEncoderReranker

logger = logging.getLogger(__name__)


class ModelServiceSettings(BaseSettings):
    model_service_token: SecretStr
    model_catalog_path: Path = Path("retrieval/config/models.json")
    dense_model_key: str = "bge-m3"
    reranker_model_key: str = "bge-reranker-v2-m3"

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    @property
    def authentication_token(self) -> str:
        value = self.model_service_token.get_secret_value()
        if len(value) < 32:
            raise ValueError("MODEL_SERVICE_TOKEN must contain at least 32 characters")
        return value


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: Literal["bge-m3"]
    input_type: Literal["query", "passage"]
    texts: list[str] = Field(min_length=1, max_length=32)


class EmbeddingResponse(BaseModel):
    model_key: str
    model_revision: str
    dimensions: int
    vectors: list[list[float]]
    truncated: list[bool]


class RerankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: Literal["bge-reranker-v2-m3"]
    query: str = Field(min_length=3, max_length=500)
    passages: list[str] = Field(min_length=1, max_length=50)


class RerankResponse(BaseModel):
    model_key: str
    model_revision: str
    scores: list[float]


class Runtime(Protocol):
    def load(self) -> None: ...

    def ready(self) -> bool: ...

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...

    def rerank(self, request: RerankRequest) -> RerankResponse: ...


def _validate_texts(values: Sequence[str], *, max_characters: int) -> None:
    if any(not value.strip() or len(value) > max_characters for value in values):
        raise ValueError("Input contains empty or oversized text")


class ModelRuntime:
    def __init__(self, settings: ModelServiceSettings) -> None:
        self.settings = settings
        self.catalog = ModelCatalog.load(settings.model_catalog_path)
        self.dense_spec = self.catalog.get(settings.dense_model_key)
        self.reranker_spec = self.catalog.get(settings.reranker_model_key)
        self.dense: DenseEncoder | None = None
        self.reranker: CrossEncoderReranker | None = None
        self.inference_lock = threading.Lock()

    def load(self) -> None:
        self.dense = create_dense_encoder(self.dense_spec)
        self.reranker = CrossEncoderReranker(self.reranker_spec)

    def ready(self) -> bool:
        return self.dense is not None and self.reranker is not None

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if not self.dense:
            raise RuntimeError("Dense model is not ready")
        _validate_texts(request.texts, max_characters=30_000)
        with self.inference_lock:
            encoded = self.dense.encode_queries(request.texts)
        return EmbeddingResponse(
            model_key=self.dense_spec.key,
            model_revision=self.dense_spec.revision,
            dimensions=self.dense.dimensions,
            vectors=encoded.vectors,
            truncated=list(encoded.truncated),
        )

    def rerank(self, request: RerankRequest) -> RerankResponse:
        if not self.reranker:
            raise RuntimeError("Reranker is not ready")
        _validate_texts((request.query, *request.passages), max_characters=30_000)
        with self.inference_lock:
            scores = self.reranker.score(request.query, request.passages)
        return RerankResponse(
            model_key=self.reranker_spec.key,
            model_revision=self.reranker_spec.revision,
            scores=scores,
        )


def create_app(
    *,
    settings: ModelServiceSettings | None = None,
    runtime: Runtime | None = None,
) -> FastAPI:
    service_settings = settings or ModelServiceSettings()  # type: ignore[call-arg]
    expected_token = service_settings.authentication_token
    model_runtime = runtime or ModelRuntime(service_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            await asyncio.to_thread(model_runtime.load)
        except Exception as exc:
            logger.error("Model service startup failed (%s)", type(exc).__name__)
            raise RuntimeError("Model service startup failed") from None
        yield

    app = FastAPI(
        title="Beken.ai Model Service",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> None:
        prefix = "Bearer "
        supplied = (
            authorization[len(prefix) :]
            if authorization and authorization.startswith(prefix)
            else ""
        )
        if not supplied or not secrets.compare_digest(supplied, expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    authentication = Annotated[None, Depends(authenticate)]

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        if not model_runtime.ready():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        return {"status": "ready"}

    @app.post("/v1/embeddings", response_model=EmbeddingResponse)
    async def embeddings(request: EmbeddingRequest, _: authentication) -> EmbeddingResponse:
        try:
            return await run_in_threadpool(model_runtime.embed, request)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
        except Exception as exc:
            logger.warning("Embedding inference failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from None

    @app.post("/v1/rerank", response_model=RerankResponse)
    async def rerank(request: RerankRequest, _: authentication) -> RerankResponse:
        try:
            return await run_in_threadpool(model_runtime.rerank, request)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
        except Exception as exc:
            logger.warning("Reranker inference failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from None

    return app
