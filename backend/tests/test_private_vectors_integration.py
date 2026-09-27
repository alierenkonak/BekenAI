from __future__ import annotations

import os
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from app.files.vectors import PrivateChunkPoint, PrivateFileVectorStore

pytestmark = pytest.mark.skipif(
    os.getenv("BEKEN_RUN_QDRANT_TESTS") != "1",
    reason="Set BEKEN_RUN_QDRANT_TESTS=1 to run Qdrant integration tests",
)


def _points(count: int) -> list[PrivateChunkPoint]:
    return [
        PrivateChunkPoint(
            chunk_id=uuid4(),
            chunk_index=index,
            vector=[1.0, float(index), 0.0, 0.5],
            truncated=False,
            page_start=index + 1,
            page_end=index + 1,
        )
        for index in range(count)
    ]


def test_private_vectors_are_scoped_per_workspace_and_deleted_per_file() -> None:
    client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"), timeout=10)
    store = PrivateFileVectorStore(
        client, dimensions=4, collection=f"beken_private_test_{uuid4().hex}"
    )
    first_workspace, second_workspace = uuid4(), uuid4()
    first_file, second_file = uuid4(), uuid4()
    try:
        store.ensure_collection()
        store.ensure_collection()  # idempotent across workers and restarts
        for workspace, file, count in (
            (first_workspace, first_file, 3),
            (second_workspace, second_file, 2),
        ):
            store.upsert(
                workspace_id=workspace,
                file_id=file,
                case_id=uuid4(),
                conversation_id=None,
                embedding_model="fake",
                points=_points(count),
            )

        assert store.count_file_points(workspace_id=first_workspace, file_id=first_file) == 3
        # The same file id under another workspace matches nothing.
        assert store.count_file_points(workspace_id=second_workspace, file_id=first_file) == 0

        store.delete_file(workspace_id=first_workspace, file_id=first_file)

        assert store.count_file_points(workspace_id=first_workspace, file_id=first_file) == 0
        assert store.count_file_points(workspace_id=second_workspace, file_id=second_file) == 2
        schema = client.get_collection(store.collection).payload_schema
        assert {"workspace_id", "file_id", "case_id", "conversation_id"} <= set(schema)
    finally:
        client.delete_collection(store.collection)


def test_deleting_from_a_missing_collection_is_a_no_op() -> None:
    client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"), timeout=10)
    store = PrivateFileVectorStore(
        client, dimensions=4, collection=f"beken_private_missing_{uuid4().hex}"
    )

    store.delete_file(workspace_id=uuid4(), file_id=uuid4())
    assert store.count_file_points(workspace_id=uuid4(), file_id=uuid4()) == 0


def test_search_only_reaches_the_allowed_files_of_one_workspace() -> None:
    client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"), timeout=10)
    store = PrivateFileVectorStore(
        client, dimensions=4, collection=f"beken_private_search_{uuid4().hex}"
    )
    workspace, other_workspace = uuid4(), uuid4()
    allowed, not_ready = uuid4(), uuid4()
    try:
        store.ensure_collection()
        owners = ((workspace, allowed), (workspace, not_ready), (other_workspace, allowed))
        for owner, file_id in owners:
            store.upsert(
                workspace_id=owner,
                file_id=file_id,
                case_id=None,
                conversation_id=uuid4(),
                embedding_model="fake",
                points=_points(2),
            )

        hits = store.search(
            workspace_id=workspace, file_ids=[allowed], vector=[1.0, 0.0, 0.0, 0.5], limit=10
        )

        assert len(hits) == 2
        assert all(-1.0 <= score <= 1.0 for _, score in hits)
        assert store.search(workspace_id=workspace, file_ids=[], vector=[1.0] * 4, limit=5) == []
    finally:
        client.delete_collection(store.collection)
