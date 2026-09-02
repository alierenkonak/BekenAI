from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from beken_retrieval.dense import DeterministicFakeEncoder
from beken_retrieval.model_catalog import ModelCatalog
from beken_retrieval.models import ChunkRecord, SearchFilters
from beken_retrieval.profile import RetrievalProfileCatalog
from beken_retrieval.qdrant_store import (
    QdrantDenseRetriever,
    QdrantIndexer,
    active_alias,
    collection_name,
)
from beken_retrieval.registry import _resolve_active_path, write_active_manifest
from beken_retrieval.scope import RetrievalScope


def record(domain: str, text: str, document_type: str = "law") -> ChunkRecord:
    return ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id=f"{domain}-{document_type}",
        domain_code=domain,
        corpus_version="v1",
        retrieval_scope_version=f"{domain}-v1",
        domain_role="core",
        document_type=document_type,
        title=text,
        text=text,
        section_type="article",
    )


class FakeRepository:
    def __init__(self, records: list[ChunkRecord]) -> None:
        self.records = {item.chunk_id: item for item in records}

    def hydrate_chunks(self, chunk_ids, *, scope):
        return {value: self.records[value] for value in chunk_ids if value in self.records}


def scope(domain: str) -> RetrievalScope:
    return RetrievalScope(
        path=Path("fixture"),
        manifest_hash="a" * 64,
        payload={
            "version": f"{domain}-v1",
            "domain": domain,
            "corpus_version": "v1",
            "review_status": "reviewed",
            "roles": {"core": {"include": True, "mode": "full_document"}},
        },
    )


def test_domain_collections_and_aliases_are_independent() -> None:
    client = QdrantClient(":memory:")
    encoder = DeterministicFakeEncoder()
    indexer = QdrantIndexer(client)
    labour_collection = collection_name(domain="labour_law", corpus_version="v1", model_key="fake")
    tax_collection = collection_name(domain="tax_law", corpus_version="v1", model_key="fake")
    indexer.build_immutable(
        collection=labour_collection,
        records=[record("labour_law", "kıdem")],
        encoder=encoder,
    )
    indexer.build_immutable(
        collection=tax_collection,
        records=[record("tax_law", "vergi")],
        encoder=encoder,
    )
    indexer.activate(collection=labour_collection, alias=active_alias("labour_law"))
    indexer.activate(collection=tax_collection, alias=active_alias("tax_law"))

    aliases = {item.alias_name: item.collection_name for item in client.get_aliases().aliases}
    assert aliases[active_alias("labour_law")] == labour_collection
    assert aliases[active_alias("tax_law")] == tax_collection


def test_qdrant_and_lexical_style_filters_use_same_record_contract() -> None:
    client = QdrantClient(":memory:")
    encoder = DeterministicFakeEncoder()
    records = [
        record("labour_law", "fazla çalışma kanun", "law"),
        record("labour_law", "fazla çalışma karar", "court_decision"),
    ]
    collection = collection_name(domain="labour_law", corpus_version="v1", model_key="fake")
    QdrantIndexer(client).build_immutable(collection=collection, records=records, encoder=encoder)
    dense = QdrantDenseRetriever(
        client=client,
        collection=collection,
        encoder=encoder,
        repository=FakeRepository(records),
        scope=scope("labour_law"),
    )

    results = dense.search(
        "fazla çalışma",
        filters=SearchFilters(document_types=("law",)),
        limit=10,
    )

    assert [hit.record.document_type for hit in results] == ["law"]


def test_model_catalog_pins_revisions_and_safe_artifacts() -> None:
    catalog = ModelCatalog.load(Path("retrieval/config/models.json"))

    assert len(catalog.get("multilingual-e5-base").revision) == 40
    assert catalog.get("multilingual-e5-base").safe_artifact.endswith(".safetensors")
    assert catalog.get("bge-m3").safe_artifact.endswith(".onnx")
    assert catalog.get("bge-m3").supporting_artifacts == ("onnx/model.onnx_data",)


def test_labour_law_profile_pins_selected_hybrid_system() -> None:
    models = ModelCatalog.load(Path("retrieval/config/models.json"))
    profile = RetrievalProfileCatalog.load(
        Path("retrieval/config/domain_profiles.json"), models=models
    ).get("labour_law")

    assert profile.lexical_backend == "bm25s"
    assert profile.dense_model == "bge-m3"
    assert profile.fusion == "rrf"
    assert profile.fusion_k == 60
    assert profile.reranker_model == "bge-reranker-v2-m3"
    assert profile.hybrid_candidate_limit == 25
    assert profile.selection_status == "owner_accepted"
    assert profile.quality_gate_status == "owner_accepted_with_latency_exception"


def test_evaluation_manifest_records_owner_acceptance_without_inventing_labels() -> None:
    payload = json.loads(Path("evals/labour_law/manifest.json").read_text(encoding="utf-8"))

    assert payload["status"] == "owner_accepted"
    assert payload["acceptance"]["evidence_status"] == "owner_attestation"
    assert payload["acceptance"]["per_passage_review_labels_imported"] is False


def test_profile_rejects_an_active_e5_manifest() -> None:
    models = ModelCatalog.load(Path("retrieval/config/models.json"))
    profile = RetrievalProfileCatalog.load(
        Path("retrieval/config/domain_profiles.json"), models=models
    ).get("labour_law")

    with pytest.raises(ValueError, match="dense model"):
        profile.validate_active_manifest(
            {
                "domain": "labour_law",
                "dense": {"model_key": "multilingual-e5-base"},
                "reranker_model_key": "bge-reranker-v2-m3",
                "hybrid_candidate_limit": 25,
            }
        )


def test_new_scope_identity_cannot_retain_a_stale_dense_index(tmp_path: Path) -> None:
    root = tmp_path / "indexes"
    common = {
        "domain": "labour_law",
        "corpus_version": "v1",
        "scope_path": "/scope.json",
    }
    write_active_manifest(
        root,
        domain="labour_law",
        updates={**common, "scope_hash": "a" * 64, "dense": {"collection": "old"}},
    )
    path = write_active_manifest(
        root,
        domain="labour_law",
        updates={**common, "scope_hash": "b" * 64, "bm25_path": "/new-bm25"},
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["bm25_path"] == "/new-bm25"
    assert "dense" not in payload


def test_dense_collection_name_changes_with_index_version() -> None:
    first = collection_name(
        domain="labour_law",
        corpus_version="v4",
        model_key="e5",
        index_version="one",
    )
    second = collection_name(
        domain="labour_law",
        corpus_version="v4",
        model_key="e5",
        index_version="two",
    )

    assert first != second


def test_active_manifest_paths_can_move_with_the_release(tmp_path: Path) -> None:
    active = tmp_path / "retrieval_data" / "labour_law" / "active.json"

    assert _resolve_active_path(active, "bm25/index") == (
        active.parent / "bm25/index"
    ).resolve()
    assert _resolve_active_path(active, "../../retrieval-scopes/labour-law-v1/manifest.json") == (
        tmp_path / "retrieval-scopes/labour-law-v1/manifest.json"
    ).resolve()
