import json
from pathlib import Path

import httpx
import pytest

from beken_ingestion.storage import (
    FilesystemRawStorage,
    StorageSecurityError,
    SupabaseRawStorage,
    validate_object_path,
)


def test_filesystem_storage_is_immutable(tmp_path: Path) -> None:
    storage = FilesystemRawStorage(tmp_path)

    assert storage.put_if_absent("global/test/ab/hash.txt", b"first", "text/plain") is True
    assert storage.put_if_absent("global/test/ab/hash.txt", b"second", "text/plain") is False
    assert (tmp_path / "global/test/ab/hash.txt").read_bytes() == b"first"
    assert storage.get("global/test/ab/hash.txt") == b"first"


@pytest.mark.parametrize("path", ["../secret", "/absolute", "global/../../secret"])
def test_storage_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError):
        validate_object_path(path)


@pytest.mark.parametrize(
    ("missing_status", "missing_body"),
    [
        (404, None),
        (400, {"statusCode": "404", "code": "NoSuchBucket"}),
    ],
)
def test_supabase_bucket_bootstrap_creates_private_bucket(
    missing_status: int, missing_body: dict[str, str] | None
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(missing_status, json=missing_body, request=request)
        return httpx.Response(200, json={"name": "legal-raw"}, request=request)

    storage = SupabaseRawStorage(
        "https://project.supabase.co",
        "test-secret-key",
        "legal-raw",
        transport=httpx.MockTransport(handler),
    )
    try:
        storage.ensure_private_bucket()
    finally:
        storage.close()

    body = json.loads(requests[1].content)
    assert body["public"] is False
    assert requests[0].headers["apikey"] == "test-secret-key"
    assert "authorization" not in requests[0].headers


def test_supabase_bucket_bootstrap_rejects_public_bucket() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"public": True}, request=request)

    storage = SupabaseRawStorage(
        "https://project.supabase.co",
        "test-secret-key",
        "legal-raw",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(StorageSecurityError):
            storage.ensure_private_bucket()
    finally:
        storage.close()


def test_supabase_private_download_uses_authenticated_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/storage/v1/object/authenticated/legal-raw/global/doc.pdf"
        assert request.headers["apikey"] == "test-secret-key"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"private", request=request)

    storage = SupabaseRawStorage(
        "https://project.supabase.co",
        "test-secret-key",
        "legal-raw",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert storage.get("global/doc.pdf") == b"private"
    finally:
        storage.close()
