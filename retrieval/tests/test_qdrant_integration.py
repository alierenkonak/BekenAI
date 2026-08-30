from __future__ import annotations

import os
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from beken_retrieval.dense import DeterministicFakeEncoder
from beken_retrieval.models import ChunkRecord
from beken_retrieval.qdrant_store import QdrantIndexer, active_alias, collection_name

pytestmark = pytest.mark.skipif(
    os.getenv("BEKEN_RUN_QDRANT_TESTS") != "1",
    reason="requires the local Qdrant service",
)


def _record(domain: str, text: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id=f"fixture-{domain}",
        domain_code=domain,
        corpus_version="fixture-v1",
        retrieval_scope_version=f"{domain}-fixture-v1",
        domain_role="core",
        document_type="law",
        title=text,
        text=text,
        section_type="article",
    )


def test_real_qdrant_keeps_domain_aliases_independent() -> None:
    client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    encoder = DeterministicFakeEncoder()
    indexer = QdrantIndexer(client)
    suffix = uuid4().hex[:10]
    collections = {
        domain: collection_name(
            domain=domain,
            corpus_version=f"fixture_{suffix}",
            model_key="fake",
            prefix="beken_test",
        )
        for domain in ("labour_law", "tax_law")
    }
    aliases = {
        domain: active_alias(domain, prefix=f"beken_test_{suffix}") for domain in collections
    }
    try:
        for domain, collection in collections.items():
            summary = indexer.build_immutable(
                collection=collection,
                records=[_record(domain, domain)],
                encoder=encoder,
            )
            assert summary["indexed"] == 1
            indexer.activate(collection=collection, alias=aliases[domain])

        actual = {
            item.alias_name: item.collection_name
            for item in client.get_aliases().aliases
            if item.alias_name in aliases.values()
        }
        assert actual == {
            aliases["labour_law"]: collections["labour_law"],
            aliases["tax_law"]: collections["tax_law"],
        }
    finally:
        for collection in collections.values():
            if client.collection_exists(collection):
                client.delete_collection(collection)
