from __future__ import annotations

import json
from pathlib import Path

from qdrant_client import QdrantClient

from beken_retrieval.bm25 import BM25LexicalRetriever
from beken_retrieval.config import RetrievalSettings
from beken_retrieval.coordinator import HybridDomainIndex
from beken_retrieval.dense import create_dense_encoder
from beken_retrieval.model_catalog import ModelCatalog
from beken_retrieval.postgres import PostgresCorpusRepository
from beken_retrieval.qdrant_store import QdrantDenseRetriever
from beken_retrieval.reranking import CrossEncoderReranker
from beken_retrieval.scope import load_scope


class FilesystemIndexRegistry:
    def __init__(self, settings: RetrievalSettings) -> None:
        self.settings = settings
        self._indexes: dict[str, HybridDomainIndex] = {}
        self._load()

    def _load(self) -> None:
        root = self.settings.retrieval_index_root
        if not root.exists():
            return
        catalog = ModelCatalog.load(self.settings.retrieval_model_catalog)
        repository = PostgresCorpusRepository(self.settings.corpus_database_url)
        qdrant = QdrantClient(
            url=self.settings.qdrant_url,
            api_key=self.settings.qdrant_secret,
            timeout=10,
        )
        for active_path in sorted(root.glob("*/active.json")):
            payload = json.loads(active_path.read_text(encoding="utf-8"))
            domain = str(payload["domain"])
            scope = load_scope(Path(payload["scope_path"]))
            if scope.domain != domain or scope.corpus_version != payload["corpus_version"]:
                raise ValueError(f"Active index/scope mismatch for {domain}")
            if payload.get("scope_hash") != scope.manifest_hash:
                raise ValueError(f"Active index/scope hash mismatch for {domain}")
            lexical = None
            bm25_path = payload.get("bm25_path")
            if bm25_path:
                lexical = BM25LexicalRetriever.load(Path(bm25_path))
            dense = None
            dense_config = payload.get("dense")
            if dense_config:
                encoder = create_dense_encoder(catalog.get(str(dense_config["model_key"])))
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
                reranker = CrossEncoderReranker(catalog.get(str(reranker_key)))
            self._indexes[domain] = HybridDomainIndex(
                domain_code=domain,
                corpus_version=str(payload["corpus_version"]),
                index_version=str(payload["index_version"]),
                lexical=lexical,
                dense=dense,
                reranker=reranker,
                hybrid_candidate_limit=int(payload.get("hybrid_candidate_limit", 50)),
            )

    def get(self, domain_code: str) -> HybridDomainIndex | None:
        return self._indexes.get(domain_code)

    def supported_domains(self) -> tuple[str, ...]:
        return tuple(sorted(self._indexes))


def write_active_manifest(
    root: Path,
    *,
    domain: str,
    updates: dict,
) -> Path:
    path = root / domain / "active.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    identity_fields = ("domain", "corpus_version", "scope_path", "scope_hash")
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
