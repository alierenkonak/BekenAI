from __future__ import annotations

import json
import ssl
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import truststore

from beken_ingestion.models import RawDocument


class SourceAdapterError(RuntimeError):
    pass


class SourceAccessBlocked(SourceAdapterError):
    """Raised when an official source requires interactive access such as CAPTCHA."""


@dataclass(frozen=True)
class SourceDocumentFailure:
    source_url: str
    source_document_id: str
    error_code: str
    error_detail: str
    retryable: bool = True


class OfficialHttpAdapter:
    allowed_hosts: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        rate_limit_seconds: float = 1.0,
        max_attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.rate_limit_seconds = rate_limit_seconds
        self.max_attempts = max_attempts
        self._last_request_at = 0.0
        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            headers={"User-Agent": "BekenAI-Ingestion/0.1 (+source-preserving research)"},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> OfficialHttpAdapter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_hosts:
            raise ValueError(f"URL is outside the official source allowlist: {url}")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self._validate_url(url)
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            try:
                response = self.client.request(method, url, **kwargs)
                self._last_request_at = time.monotonic()
                self._validate_url(str(response.url))
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = min(float(response.headers.get("Retry-After", "1")), 30.0)
                    if attempt < self.max_attempts:
                        time.sleep(max(retry_after, self.rate_limit_seconds))
                        continue
                response.raise_for_status()
                return response
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    time.sleep(self.rate_limit_seconds * attempt)
        if isinstance(last_error, httpx.HTTPStatusError):
            status = last_error.response.status_code
            path = last_error.request.url.path
            detail = f"HTTP {status} at {path}"
        else:
            detail = type(last_error).__name__
        raise SourceAdapterError(f"Official source request failed: {detail}")


class MevzuatAdapter(OfficialHttpAdapter):
    allowed_hosts = frozenset({"www.mevzuat.gov.tr", "mevzuat.gov.tr"})

    def fetch(self, source: dict[str, Any]) -> RawDocument:
        url = str(source["url"])
        response = self.request("GET", url)
        media_type = response.headers.get("Content-Type", "application/octet-stream").split(
            ";", 1
        )[0]
        return RawDocument(
            source_name="mevzuat",
            source_document_id=str(source["source_document_id"]),
            source_url=url,
            media_type=media_type,
            content=response.content,
            retrieved_at=datetime.now(UTC),
            metadata=dict(source.get("metadata") or {}),
        )


class YargitayAdapter(OfficialHttpAdapter):
    allowed_hosts = frozenset({"karararama.yargitay.gov.tr"})
    base_url = "https://karararama.yargitay.gov.tr"

    @staticmethod
    def _raise_for_source_error(payload: Any) -> None:
        serialized = (
            json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
        )
        lowered = serialized.casefold()
        if "captcha" in lowered or "robot değilim" in lowered:
            raise SourceAccessBlocked(
                "Yargıtay requires interactive CAPTCHA; import stopped safely"
            )
        if isinstance(payload, dict) and payload.get("data") is None:
            raise SourceAdapterError("Yargıtay returned an empty/error response")

    def search(
        self,
        query: str,
        *,
        page_size: int = 10,
        start_page: int = 1,
        max_documents: int = 100,
    ) -> Iterator[tuple[RawDocument | SourceDocumentFailure, dict[str, Any]]]:
        self.request("GET", f"{self.base_url}/")
        form = {"arananKelime": query}
        initial = self.request("POST", f"{self.base_url}/arama", json={"data": form})
        self._raise_for_source_error(initial.text)
        yielded = 0
        page = start_page
        while yielded < max_documents:
            request_data = {"data": {**form, "pageSize": str(page_size), "pageNumber": str(page)}}
            response = self.request("POST", f"{self.base_url}/aramalist", json=request_data)
            payload = response.json()
            self._raise_for_source_error(payload)
            result = payload.get("data") or {}
            rows = result.get("data") or []
            if not rows:
                return
            for index, row in enumerate(rows):
                if yielded >= max_documents:
                    return
                document_id = str(row["id"])
                document_url = f"{self.base_url}/getDokuman?id={document_id}"
                checkpoint = {"query": query, "page": page, "row": index + 1}
                try:
                    document_response = self.request(
                        "GET", f"{self.base_url}/getDokuman", params={"id": document_id}
                    )
                    document_payload = document_response.json()
                    self._raise_for_source_error(document_payload)
                except SourceAccessBlocked:
                    raise
                except (SourceAdapterError, ValueError) as exc:
                    yield (
                        SourceDocumentFailure(
                            source_url=document_url,
                            source_document_id=document_id,
                            error_code=type(exc).__name__,
                            error_detail=str(exc),
                        ),
                        checkpoint,
                    )
                    yielded += 1
                    continue
                html = str(document_payload["data"])
                yield (
                    RawDocument(
                        source_name="yargitay",
                        source_document_id=document_id,
                        source_url=document_url,
                        media_type="text/html",
                        content=html.encode("utf-8"),
                        metadata={
                            "source_kind": "court_decision",
                            "document_type": "court_decision",
                            "domain": "labour_law",
                            "authority": "Yargıtay",
                            "chamber": row.get("daire"),
                            "case_number": row.get("esasNo"),
                            "decision_number": row.get("kararNo"),
                            "document_date": row.get("kararTarihi"),
                            "domain_metadata": {"pilot_topic": "termination_reinstatement"},
                        },
                    ),
                    checkpoint,
                )
                yielded += 1
            page += 1


class LocalFileAdapter:
    def fetch(self, path: Path, metadata: dict[str, Any]) -> RawDocument:
        resolved = path.resolve(strict=True)
        suffix = resolved.suffix.casefold()
        media_type = {
            ".pdf": "application/pdf",
            ".html": "text/html",
            ".htm": "text/html",
            ".txt": "text/plain",
        }.get(suffix)
        if not media_type:
            raise ValueError(f"Unsupported local document type: {suffix}")
        return RawDocument(
            source_name=str(metadata.get("source_name") or "manual"),
            source_document_id=str(metadata.get("source_document_id") or resolved.stem),
            source_url=resolved.as_uri(),
            media_type=media_type,
            content=resolved.read_bytes(),
            metadata=metadata,
        )
