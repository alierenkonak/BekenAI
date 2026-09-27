from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.api.files import _safe_storage_name
from app.core.repository import get_repository
from app.core.storage import (
    StorageError,
    StorageSizeLimitExceeded,
    _read_bounded_body,
    get_storage,
)
from app.files.extraction import DOCX
from app.main import app
from app.worker import detect_file


class _ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def test_storage_name_is_safe_and_keeps_expected_extension() -> None:
    assert _safe_storage_name("İşe İade / Karar?.PDF".replace("/", "-"), "application/pdf") == (
        "Ise-Iade-Karar.pdf"
    )


def test_file_signature_validation() -> None:
    assert detect_file(b"%PDF-1.7\nfixture", "application/pdf") == "application/pdf"
    assert detect_file("Türkçe metin".encode(), "text/plain") == "text/plain"
    with pytest.raises(ValueError, match="invalid_pdf_signature"):
        detect_file(b"not a pdf", "application/pdf")
    with pytest.raises(ValueError, match="invalid_text_file"):
        detect_file(b"bad\x00text", "text/plain")


@pytest.mark.asyncio
async def test_storage_body_reader_accepts_exact_declared_size() -> None:
    response = httpx.Response(200, content=b"1234")

    assert await _read_bounded_body(response, 4) == b"1234"


@pytest.mark.asyncio
async def test_storage_body_reader_rejects_declared_or_streamed_oversize() -> None:
    response = httpx.Response(200, content=b"12345")

    with pytest.raises(StorageSizeLimitExceeded, match="file_size_mismatch"):
        await _read_bounded_body(response, 4)

    chunked_response = httpx.Response(200, stream=_ChunkedStream(b"12", b"345"))
    with pytest.raises(StorageSizeLimitExceeded, match="file_size_mismatch"):
        await _read_bounded_body(chunked_response, 4)


@pytest.mark.asyncio
async def test_storage_body_reader_rejects_invalid_content_length() -> None:
    response = httpx.Response(200, headers={"content-length": "invalid"}, content=b"1")

    with pytest.raises(StorageError, match="invalid_storage_content_length"):
        await _read_bounded_body(response, 4)


class _FileRepository:
    def __init__(self, file: dict | None = None) -> None:
        self.file = file or {}
        self.intents: list[dict] = []
        self.reindexed: list = []

    async def create_file_intent(self, user_id, **values):
        self.intents.append(values)
        return {
            "id": "file-id",
            "storage_bucket": "case-files",
            "storage_path": f"{user_id}/w/conversations/c/file-id/{values['safe_name']}",
        }

    async def get_file(self, user_id, file_id):
        return self.file

    async def request_file_reindex(self, user_id, file_id):
        self.reindexed.append(file_id)
        return {**self.file, "status": "indexing"}


def _files_client(repository: _FileRepository) -> httpx.AsyncClient:
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_storage] = lambda: SimpleNamespace(
        signed_download_url=AsyncMock(return_value="https://storage.example.test/signed")
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_docx_uploads_keep_a_docx_extension() -> None:
    assert _safe_storage_name("Dilekçe.docx", DOCX) == "Dilekce.docx"


@pytest.mark.asyncio
async def test_chat_uploads_are_scoped_to_the_conversation() -> None:
    repository = _FileRepository()
    conversation_id = uuid4()
    async with _files_client(repository) as client:
        response = await client.post(
            f"/conversations/{conversation_id}/files/upload-intent",
            json={"filename": "Fesih.docx", "media_type": DOCX, "size_bytes": 2048},
        )

    assert response.status_code == 201
    assert response.json()["upload"]["upsert"] is False
    [intent] = repository.intents
    assert intent["conversation_id"] == conversation_id and intent["case_id"] is None
    assert intent["media_type"] == DOCX


@pytest.mark.asyncio
async def test_legacy_word_documents_are_rejected_before_upload() -> None:
    async with _files_client(_FileRepository()) as client:
        response = await client.post(
            f"/cases/{uuid4()}/files/upload-intent",
            json={"filename": "eski.doc", "media_type": "application/msword", "size_bytes": 10},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "verified", "expected"),
    [
        ("ready", 10, 200),
        ("indexing", 10, 200),
        ("failed", 10, 200),  # e.g. a scanned PDF: unusable for answers, still the user's file
        ("failed", None, 409),  # never verified: we cannot vouch for the stored bytes
        ("delete_pending", 10, 409),
    ],
)
async def test_download_requires_verified_bytes(status, verified, expected) -> None:
    repository = _FileRepository(
        {"status": status, "verified_size_bytes": verified, "storage_path": "u/w/c/f/a.pdf"}
    )
    async with _files_client(repository) as client:
        response = await client.post(f"/files/{uuid4()}/download-url")

    assert response.status_code == expected


@pytest.mark.asyncio
async def test_reindex_endpoint_requeues_the_file() -> None:
    repository = _FileRepository({"status": "failed", "verified_size_bytes": 10})
    file_id = uuid4()
    async with _files_client(repository) as client:
        response = await client.post(f"/files/{file_id}/reindex")

    assert response.status_code == 202
    assert response.json()["status"] == "indexing"
    assert repository.reindexed == [file_id]
