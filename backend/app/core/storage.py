from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import Settings, get_settings


class StorageError(RuntimeError):
    pass


class SupabaseStorage:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url:
            raise ValueError("SUPABASE_URL is required")
        parts = urlsplit(settings.supabase_url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("SUPABASE_URL must be an absolute HTTPS URL without credentials")
        self.base_url = settings.supabase_url.rstrip("/")
        self.bucket = settings.case_files_bucket
        self.secret = settings.supabase_backend_secret
        self.maximum_bytes = settings.case_file_max_bytes

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"apikey": self.secret}
        # Legacy service_role keys are JWTs. New sb_secret_* keys are API keys and
        # must not be presented as bearer JWTs.
        if self.secret.count(".") == 2:
            headers["Authorization"] = f"Bearer {self.secret}"
        return headers

    def _object_path(self, storage_path: str) -> str:
        safe_bucket = quote(self.bucket, safe="")
        safe_path = quote(storage_path, safe="/")
        return f"/storage/v1/object/{safe_bucket}/{safe_path}"

    async def download(self, storage_path: str) -> bytes:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(60.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(self._object_path(storage_path), headers=self._headers)
        if response.status_code != 200:
            raise StorageError("storage_object_unavailable")
        if len(response.content) > self.maximum_bytes:
            raise StorageError("file_too_large")
        return response.content

    async def delete(self, storage_path: str) -> None:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(20.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.delete(self._object_path(storage_path), headers=self._headers)
        if response.status_code not in {200, 204, 404}:
            raise StorageError("storage_delete_failed")

    async def signed_download_url(self, storage_path: str, *, expires: int) -> str:
        safe_bucket = quote(self.bucket, safe="")
        safe_path = quote(storage_path, safe="/")
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"/storage/v1/object/sign/{safe_bucket}/{safe_path}",
                headers=self._headers,
                json={"expiresIn": expires},
            )
        if response.status_code != 200:
            raise StorageError("signed_url_failed")
        signed_path = response.json().get("signedURL") or response.json().get("signedUrl")
        if not isinstance(signed_path, str) or not signed_path.startswith("/"):
            raise StorageError("invalid_signed_url")
        return f"{self.base_url}/storage/v1{signed_path}"


@lru_cache
def get_storage() -> SupabaseStorage:
    return SupabaseStorage(get_settings())
