from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from beken_retrieval.dense import EncodedBatch

from app.core.repository import ConflictError
from app.files.extraction import ExtractionError
from app.files.ingestion import FileIngestionService, document_title
from app.files.vectors import PrivateFileVectorStore

PARAGRAPH = (
    "Davalı işveren 15.06.2023 tarihli bildirimle iş sözleşmesini performans düşüklüğü "
    "gerekçesiyle feshetmiştir. Fesihten önce savunma alınmamıştır."
)
DOCUMENT = "\n\n".join(["AÇIKLAMALAR", *(f"{i}. {PARAGRAPH}" for i in range(1, 30))]).encode()


class FakeRepository:
    def __init__(self, file: dict, *, still_indexing_after: int | None = None) -> None:
        self.file = file
        self.progress: list[dict] = []
        self.completed: dict | None = None
        self.still_indexing_after = still_indexing_after

    async def get_worker_file(self, file_id):
        assert file_id == self.file["id"]
        return self.file

    async def report_file_progress(self, job_id, file_id, **values) -> bool:
        self.progress.append(values)
        limit = self.still_indexing_after
        return limit is None or len(self.progress) <= limit

    async def complete_file_indexing(self, job_id, file_id, **values) -> None:
        self.completed = {"job_id": job_id, "file_id": file_id, **values}


class FakeStorage:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.downloads: list[tuple[str, int]] = []

    async def download(self, path: str, *, maximum_bytes: int) -> bytes:
        self.downloads.append((path, maximum_bytes))
        return self.data


class FakeEmbedder:
    model_key = "bge-m3"
    dimensions = 4

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.texts: list[str] = []

    def embed_passages(self, texts):
        if self.fail:
            raise RuntimeError("model service down")
        self.texts.extend(texts)
        return EncodedBatch(
            vectors=[[0.5, 0.5, 0.5, 0.5] for _ in texts], truncated=(False,) * len(texts)
        )


class FakeVectors:
    def __init__(self) -> None:
        self.ensured = 0
        self.upserts: list[dict] = []
        self.deletes: list[dict] = []

    def ensure_collection(self) -> None:
        self.ensured += 1

    def upsert(self, **values) -> None:
        self.upserts.append(values)

    def delete_file(self, **values) -> None:
        self.deletes.append(values)


def _file(data: bytes = DOCUMENT, **overrides) -> dict:
    file = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "case_id": uuid4(),
        "conversation_id": None,
        "status": "indexing",
        "storage_path": "user/workspace/case/file/fesih.txt",
        "original_name": "Fesih_Bildirimi.txt",
        "declared_media_type": "text/plain",
        "detected_media_type": "text/plain",
        "expected_size_bytes": len(data),
        "verified_size_bytes": len(data),
        "content_hash": hashlib.sha256(data).hexdigest(),
    }
    file.update(overrides)
    return file


def _service(repository, *, data: bytes = DOCUMENT, embedder=None, vectors=None):
    return FileIngestionService(
        repository=repository,
        storage=FakeStorage(data),
        embedder=embedder or FakeEmbedder(),
        vectors=vectors or FakeVectors(),
        batch_size=4,
    )


@pytest.mark.asyncio
async def test_ingest_embeds_every_chunk_into_the_private_scope_and_completes() -> None:
    file = _file()
    repository = FakeRepository(file)
    embedder, vectors = FakeEmbedder(), FakeVectors()
    service = _service(repository, embedder=embedder, vectors=vectors)

    await service.ingest({"id": "job-id", "subject_id": file["id"]})

    completed = repository.completed
    assert completed is not None
    chunks, chunk_ids = completed["chunks"], completed["chunk_ids"]
    total = len(chunks)
    assert total > 1 and len(set(chunk_ids)) == total
    assert repository.progress[0]["chunks_total"] == total
    assert repository.progress[-1] == {"chunks_done": total}
    # A retried job starts from a clean slate before writing anything.
    assert vectors.ensured == 1
    assert vectors.deletes == [{"workspace_id": file["workspace_id"], "file_id": file["id"]}]
    points = [point for upsert in vectors.upserts for point in upsert["points"]]
    assert sorted(point.chunk_id for point in points) == sorted(chunk_ids)
    assert all(
        upsert["workspace_id"] == file["workspace_id"]
        and upsert["file_id"] == file["id"]
        and upsert["case_id"] == file["case_id"]
        and upsert["embedding_model"] == "bge-m3"
        for upsert in vectors.upserts
    )
    assert all(text.startswith("Belge: Fesih Bildirimi\n") for text in embedder.texts)
    assert completed["embedding_model"] == "bge-m3"


@pytest.mark.asyncio
async def test_ingest_stops_and_cleans_up_when_the_file_is_deleted_midway() -> None:
    file = _file()
    repository = FakeRepository(file, still_indexing_after=1)
    vectors = FakeVectors()

    with pytest.raises(ConflictError, match="file_not_indexing"):
        await _service(repository, vectors=vectors).ingest({"id": "job", "subject_id": file["id"]})

    assert repository.completed is None
    assert len(vectors.deletes) == 2  # the clean-slate delete and the cleanup


@pytest.mark.asyncio
async def test_embedding_failure_discards_partial_vectors() -> None:
    file = _file()
    vectors = FakeVectors()
    service = _service(FakeRepository(file), embedder=FakeEmbedder(fail=True), vectors=vectors)

    with pytest.raises(RuntimeError, match="model service down"):
        await service.ingest({"id": "job", "subject_id": file["id"]})

    assert len(vectors.deletes) == 2


@pytest.mark.asyncio
async def test_ingest_refuses_bytes_that_differ_from_the_verified_upload() -> None:
    file = _file(content_hash="0" * 64)
    vectors = FakeVectors()

    with pytest.raises(ExtractionError, match="file_content_changed"):
        await _service(FakeRepository(file), vectors=vectors).ingest(
            {"id": "job", "subject_id": file["id"]}
        )
    assert vectors.upserts == []


@pytest.mark.asyncio
async def test_ingest_skips_files_that_are_no_longer_indexing() -> None:
    file = _file(status="delete_pending")
    service = _service(FakeRepository(file))

    with pytest.raises(ConflictError, match="file_not_indexing"):
        await service.ingest({"id": "job", "subject_id": file["id"]})
    assert service.storage.downloads == []


def test_private_vectors_can_never_target_a_global_collection() -> None:
    with pytest.raises(ValueError, match="beken_private"):
        PrivateFileVectorStore(object(), dimensions=4, collection="beken_global_labour_law_active")


def test_document_title_comes_from_the_file_name() -> None:
    assert document_title("İşe_İade_Dilekçesi.pdf") == "İşe İade Dilekçesi"
    assert document_title("notlar") == "notlar"
