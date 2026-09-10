import httpx
import pytest

from app.api.files import _safe_storage_name
from app.core.storage import StorageError, StorageSizeLimitExceeded, _read_bounded_body
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
