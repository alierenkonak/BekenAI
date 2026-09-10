from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
import socket
import time

from app.api.search import _load_search_coordinator
from app.chat.grounded import GroundedChatService
from app.core.config import get_settings
from app.core.database import get_database
from app.core.repository import AppRepository, CitationIntegrityError, ConflictError
from app.core.storage import StorageError, SupabaseStorage
from app.llm.gemini import get_llm_provider
from app.llm.provider import PermanentLLMError, TransientLLMError

logger = logging.getLogger("bekenai.worker")


def detect_file(data: bytes, declared: str) -> str:
    if declared == "application/pdf":
        if b"%PDF-" not in data[:1024]:
            raise ValueError("invalid_pdf_signature")
        return "application/pdf"
    if declared == "text/plain":
        if b"\x00" in data:
            raise ValueError("invalid_text_file")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid_text_encoding") from exc
        return "text/plain"
    raise ValueError("unsupported_media_type")


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.repository = AppRepository(get_database())
        self.storage = SupabaseStorage(self.settings)
        self.worker_id = f"{socket.gethostname()}:{id(self)}"
        self.stopping = asyncio.Event()

    async def run(self) -> None:
        next_recovery = 0.0
        while not self.stopping.is_set():
            now = time.monotonic()
            if now >= next_recovery:
                recovered = await self.repository.recover_stale_jobs(
                    self.settings.chat_worker_stale_minutes
                )
                if recovered:
                    logger.info("Recovered %d stale jobs", recovered)
                next_recovery = now + 60.0
            job = await self.repository.claim_job(self.worker_id)
            if job is None:
                try:
                    await asyncio.wait_for(
                        self.stopping.wait(), timeout=self.settings.chat_worker_poll_seconds
                    )
                except TimeoutError:
                    pass
                continue
            await self._process(job)

    async def _process(self, job: dict) -> None:
        try:
            if job["kind"] == "chat_generation":
                await self._chat(job)
            elif job["kind"] == "file_verification":
                await self._verify_file(job)
            elif job["kind"] == "file_deletion":
                await self._delete_file(job)
            else:
                raise PermanentLLMError("unsupported_job_kind")
        except TransientLLMError:
            await self.repository.fail_job(
                job, error_code="provider_temporarily_unavailable", retryable=True
            )
        except StorageError:
            await self.repository.fail_job(
                job, error_code="storage_temporarily_unavailable", retryable=True
            )
        except ConflictError:
            logger.info("Job %s was cancelled or superseded", job["id"])
        except Exception as exc:
            logger.warning("Job failed safely (%s)", type(exc).__name__)
            await self.repository.fail_job(job, error_code=self._safe_error(exc), retryable=False)

    async def _chat(self, job: dict) -> None:
        work = await self.repository.get_chat_work(job["subject_id"])
        service = GroundedChatService(_load_search_coordinator(), get_llm_provider(), self.settings)
        result = await service.answer(
            message=work["user_message"],
            retrieval_query=work["retrieval_query"],
            domain=work["domain_code"],
            include_doctrine=work["include_doctrine"],
            history=work["history"],
        )
        await self.repository.complete_generation(job["subject_id"], result)

    async def _verify_file(self, job: dict) -> None:
        file = await self.repository.get_worker_file(job["subject_id"])
        data = await self.storage.download(
            file["storage_path"], maximum_bytes=file["expected_size_bytes"]
        )
        if len(data) != file["expected_size_bytes"]:
            raise ValueError("file_size_mismatch")
        media_type = detect_file(data, file["declared_media_type"])
        await self.repository.complete_file_verification(
            job["id"],
            file["id"],
            size=len(data),
            media_type=media_type,
            content_hash=hashlib.sha256(data).hexdigest(),
        )

    async def _delete_file(self, job: dict) -> None:
        file = await self.repository.get_worker_file(job["subject_id"])
        await self.storage.delete(file["storage_path"])
        await self.repository.complete_file_deletion(job["id"], file["id"])

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, PermanentLLMError):
            return (
                str(exc)
                if str(exc)
                in {
                    "invalid_structured_output",
                    "invalid_support_output",
                    "incomplete_support_output",
                    "invalid_source_id",
                    "duplicate_claim_id",
                    "unexpected_doctrine_answer",
                }
                else "generation_failed"
            )
        if isinstance(exc, CitationIntegrityError):
            return "citation_integrity_failed"
        if isinstance(exc, ValueError) and str(exc) in {
            "invalid_pdf_signature",
            "invalid_text_file",
            "invalid_text_encoding",
            "unsupported_media_type",
            "file_size_mismatch",
        }:
            return str(exc)
        return "job_failed"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # HTTP client INFO records contain private Storage paths and request URLs.
    for name in ("httpx", "httpcore", "google_genai", "google.genai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    worker = Worker()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, worker.stopping.set)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
