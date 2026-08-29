from __future__ import annotations

import ssl
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote

import httpx
import truststore


class StorageSecurityError(RuntimeError):
    """Raised when the configured raw bucket is unexpectedly public."""


class RawStorage(Protocol):
    def put_if_absent(self, object_path: str, content: bytes, media_type: str) -> bool:
        """Store immutable content, returning False when it already exists."""

    def get(self, object_path: str) -> bytes:
        """Read an immutable object through the configured private access path."""

    def move(self, source_path: str, destination_path: str) -> None:
        """Move an immutable object to a new path without changing its bytes."""


def validate_object_path(object_path: str) -> PurePosixPath:
    path = PurePosixPath(object_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Unsafe storage object path")
    return path


class FilesystemRawStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def put_if_absent(self, object_path: str, content: bytes, media_type: str) -> bool:
        del media_type
        safe_path = validate_object_path(object_path)
        destination = (self.root / Path(*safe_path.parts)).resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError("Storage path escapes configured root")
        if destination.exists():
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return True

    def get(self, object_path: str) -> bytes:
        safe_path = validate_object_path(object_path)
        source = (self.root / Path(*safe_path.parts)).resolve()
        if not source.is_relative_to(self.root):
            raise ValueError("Storage path escapes configured root")
        return source.read_bytes()

    def move(self, source_path: str, destination_path: str) -> None:
        safe_source = validate_object_path(source_path)
        safe_destination = validate_object_path(destination_path)
        source = (self.root / Path(*safe_source.parts)).resolve()
        destination = (self.root / Path(*safe_destination.parts)).resolve()
        if not source.is_relative_to(self.root) or not destination.is_relative_to(self.root):
            raise ValueError("Storage path escapes configured root")
        if destination.exists():
            raise FileExistsError(f"Storage destination already exists: {destination_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)


class SupabaseRawStorage:
    def __init__(
        self,
        project_url: str,
        secret_key: str,
        bucket: str,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not project_url.startswith("https://"):
            raise ValueError("Supabase Storage requires an HTTPS project URL")
        self.project_url = project_url.rstrip("/")
        self.bucket = bucket
        self._client = httpx.Client(
            base_url=f"{self.project_url}/storage/v1",
            timeout=timeout_seconds,
            transport=transport,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            headers={"apikey": secret_key},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SupabaseRawStorage:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def ensure_private_bucket(self) -> None:
        response = self._client.get(f"/bucket/{quote(self.bucket, safe='')}")
        missing_bucket = response.status_code == 404
        if response.status_code == 400:
            try:
                error = response.json()
            except ValueError:
                error = {}
            missing_bucket = error.get("code") == "NoSuchBucket"
        if missing_bucket:
            response = self._client.post(
                "/bucket",
                json={
                    "id": self.bucket,
                    "name": self.bucket,
                    "public": False,
                    "file_size_limit": 52_428_800,
                    "allowed_mime_types": [
                        "application/pdf",
                        "text/html",
                        "application/xhtml+xml",
                        "text/plain",
                    ],
                },
            )
            response.raise_for_status()
            return
        response.raise_for_status()
        if response.json().get("public") is not False:
            raise StorageSecurityError(f"Storage bucket {self.bucket!r} must be private")

    def put_if_absent(self, object_path: str, content: bytes, media_type: str) -> bool:
        safe_path = validate_object_path(object_path)
        encoded_path = "/".join(quote(part, safe="") for part in safe_path.parts)
        response = self._client.post(
            f"/object/{quote(self.bucket, safe='')}/{encoded_path}",
            content=content,
            headers={"Content-Type": media_type, "x-upsert": "false"},
        )
        if response.status_code in {400, 409}:
            detail = response.text.casefold()
            duplicate_markers = ("duplicate", "already exists", "resource already exists")
            if any(marker in detail for marker in duplicate_markers):
                return False
        response.raise_for_status()
        return True

    def get(self, object_path: str) -> bytes:
        safe_path = validate_object_path(object_path)
        encoded_path = "/".join(quote(part, safe="") for part in safe_path.parts)
        response = self._client.get(
            f"/object/authenticated/{quote(self.bucket, safe='')}/{encoded_path}"
        )
        response.raise_for_status()
        return response.content

    def move(self, source_path: str, destination_path: str) -> None:
        safe_source = validate_object_path(source_path)
        safe_destination = validate_object_path(destination_path)
        response = self._client.post(
            "/object/move",
            json={
                "bucketId": self.bucket,
                "sourceKey": str(safe_source),
                "destinationKey": str(safe_destination),
            },
        )
        response.raise_for_status()
