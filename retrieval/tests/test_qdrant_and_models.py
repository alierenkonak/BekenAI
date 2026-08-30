from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from qdrant_client import QdrantClient

from beken_retrieval.dense import DeterministicFakeEncoder
from beken_retrieval.model_catalog import ModelCatalog
from beken_retrieval.models import ChunkRecord, SearchFilters
from beken_retrieval.qdrant_store import (
    QdrantDenseRetriever,
    QdrantIndexer,
    active_alias,
    collection_name,
)
from beken_retrieval.registry import write_active_manifest
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
