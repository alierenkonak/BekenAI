from __future__ import annotations

import json
from pathlib import Path

from qdrant_client import QdrantClient

from beken_retrieval.bm25 import BM25LexicalRetriever
from beken_retrieval.config import RetrievalSettings
from beken_retrieval.coordinator import HybridDomainIndex
from beken_retrieval.model_catalog import ModelCatalog
from beken_retrieval.postgres import PostgresCorpusRepository
from beken_retrieval.profile import RetrievalProfileCatalog
from beken_retrieval.qdrant_store import QdrantDenseRetriever
from beken_retrieval.remote_inference import (
    RemoteDenseEncoder,
    RemoteInferenceClient,
    RemoteReranker,
)
from beken_retrieval.scope import load_scope


def _resolve_active_path(active_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (active_path.parent / path).resolve()


class FilesystemIndexRegistry:
    def __init__(self, settings: RetrievalSettings) -> None:
        self.settings = settings
        self._indexes: dict[tuple[str, str], HybridDomainIndex] = {}
        self._load()

    def _load(self) -> None:
        root = self.settings.retrieval_index_root
        if not root.exists():
            return
        catalog = ModelCatalog.load(self.settings.retrieval_model_catalog)
        profiles = RetrievalProfileCatalog.load(
            self.settings.retrieval_profile_catalog, models=catalog
        )
        repository = PostgresCorpusRepository(self.settings.corpus_database_url)
        qdrant = QdrantClient(
            url=self.settings.qdrant_url,
            api_key=self.settings.qdrant_secret,
            timeout=10,
        )
        remote_client: RemoteInferenceClient | None = None

        def get_remote_client() -> RemoteInferenceClient:
            nonlocal remote_client
            if remote_client is None:
                remote_client = RemoteInferenceClient(
                    base_url=self.settings.model_inference_base_url,
                    token=self.settings.model_inference_secret,
                    timeout_seconds=self.settings.model_inference_timeout_seconds,
                )
            return remote_client

        active_paths = [
            *root.glob("*/active.json"),
            *root.glob("*/channels/*/active.json"),
        ]
        for active_path in sorted(active_paths):
            payload = json.loads(active_path.read_text(encoding="utf-8"))
            domain = str(payload["domain"])
            channel = str(payload.get("channel") or "primary")
            profile = profiles.get(domain)
            profile.validate_active_manifest(payload)
            scope = load_scope(_resolve_active_path(active_path, str(payload["scope_path"])))
            if scope.version != profile.scope_for_channel(channel):
                raise ValueError(
                    f"Active scope does not match retrieval profile for {domain}/{channel}"
                )
            if scope.channel != channel:
                raise ValueError(f"Active index channel mismatch for {domain}/{channel}")
            if scope.domain != domain or scope.corpus_version != payload["corpus_version"]:
                raise ValueError(f"Active index/scope mismatch for {domain}")
            if payload.get("scope_hash") != scope.manifest_hash:
                raise ValueError(f"Active index/scope hash mismatch for {domain}")
            lexical = None
            bm25_path = payload.get("bm25_path")
            if bm25_path:
                lexical = BM25LexicalRetriever.load(
                    _resolve_active_path(active_path, str(bm25_path))
                )
            dense = None
            dense_config = payload.get("dense")
            if dense_config:
                encoder = RemoteDenseEncoder(
                    catalog.get(str(dense_config["model_key"])), get_remote_client()
                )
                dense = QdrantDenseRetriever(
                    client=qdrant,
                    collection=str(dense_config["collection"]),
                    encoder=encoder,
                    repository=repository,
                    scope=scope,
                )
            reranker = None
            reranker_key = payload.get("reranker_model_key")
            if reranker_key:
                reranker = RemoteReranker(catalog.get(str(reranker_key)), get_remote_client())
            self._indexes[(domain, channel)] = HybridDomainIndex(
                domain_code=domain,
                corpus_version=str(payload["corpus_version"]),
                index_version=str(payload["index_version"]),
                channel=channel,
                lexical=lexical,
                dense=dense,
                reranker=reranker,
                hybrid_candidate_limit=profile.hybrid_candidate_limit,
                rrf_k=profile.fusion_k,
            )

    def get(
        self, domain_code: str, channel: str = "primary"
    ) -> HybridDomainIndex | None:
        return self._indexes.get((domain_code, channel))

    def supported_domains(self, channel: str = "primary") -> tuple[str, ...]:
        return tuple(sorted(domain for domain, lane in self._indexes if lane == channel))


def write_active_manifest(
    root: Path,
    *,
    domain: str,
    channel: str = "primary",
    updates: dict,
) -> Path:
    path = (
        root / domain / "active.json"
        if channel == "primary"
        else root / domain / "channels" / channel / "active.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    identity_fields = (
        "domain",
        "channel",
        "corpus_version",
        "scope_path",
        "scope_hash",
    )
    if payload and any(
        key in updates and payload.get(key) != updates[key] for key in identity_fields
    ):
        payload = {}
    payload.update(updates)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path
