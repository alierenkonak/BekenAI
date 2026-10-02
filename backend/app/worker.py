from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
import socket
import time
from collections.abc import Sequence
from functools import cached_property

from beken_retrieval.config import get_settings as get_retrieval_settings
from beken_retrieval.model_catalog import ModelCatalog, ModelSpec
from beken_retrieval.remote_inference import (
    RemoteDenseEncoder,
    RemoteInferenceClient,
    TransientInferenceError,
)
from qdrant_client import QdrantClient

from app.api.search import _load_search_coordinator
from app.chat.analysis import CaseAnalysisService
from app.chat.grounded import GroundedChatService
from app.chat.research import DeepResearchService
from app.core.config import get_settings
from app.core.database import get_database
from app.core.repository import AppRepository, CitationIntegrityError, ConflictError
from app.core.storage import StorageError, SupabaseStorage
from app.files.extraction import detect_media_type as detect_file
from app.files.ingestion import FileIngestionService, RemotePassageEmbedder
from app.files.retrieval import PrivateFileRetriever, PrivateScope, RemotePassageReranker
from app.files.vectors import PrivateFileVectorStore, VectorStoreUnavailable
from app.llm.gemini import get_llm_provider
from app.llm.provider import PermanentLLMError, TransientLLMError
from app.web.search import (
    SAFE_WEB_SEARCH_ERRORS,
    TavilyWebSearch,
    TransientWebSearchError,
    WebSearchError,
)

logger = logging.getLogger("bekenai.worker")

# Two lanes share one process: a long document never holds up a chat answer.
INTERACTIVE_JOB_KINDS = ("chat_generation", "file_verification", "file_deletion")
INGEST_JOB_KINDS = ("file_ingest",)
_SAFE_FILE_ERRORS = frozenset(
    {
        "invalid_pdf_signature",
        "invalid_text_file",
        "invalid_text_encoding",
        "invalid_docx",
        "unsupported_media_type",
        "file_size_mismatch",
        "file_content_changed",
        "encrypted_pdf",
        "unreadable_pdf",
        "scanned_pdf_not_supported",
        "empty_document",
        "too_many_pages",
        "document_too_large",
        "case_has_no_ready_files",
    }
)


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.repository = AppRepository(get_database())
        self.storage = SupabaseStorage(self.settings)
        self.worker_id = f"{socket.gethostname()}:{id(self)}"
        self.stopping = asyncio.Event()

    @cached_property
    def _embedding_spec(self) -> ModelSpec:
        catalog = ModelCatalog.load(get_retrieval_settings().retrieval_model_catalog)
        return catalog.get(self.settings.private_file_embedding_model)

    @cached_property
    def private_vectors(self) -> PrivateFileVectorStore:
        # Deletion needs only Qdrant, so it keeps working without the model service.
        settings = get_retrieval_settings()
        return PrivateFileVectorStore(
            QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_secret, timeout=30),
            dimensions=int(self._embedding_spec.dimensions or 0),
        )

    @staticmethod
    def _inference_client() -> RemoteInferenceClient:
        # One client per lane: the two lanes call the model service from separate threads.
        settings = get_retrieval_settings()
        return RemoteInferenceClient(
            base_url=settings.model_inference_base_url,
            token=settings.model_inference_secret,
            timeout_seconds=settings.model_inference_timeout_seconds,
        )

    @cached_property
    def private_retriever(self) -> PrivateFileRetriever:
        client = self._inference_client()
        catalog = ModelCatalog.load(get_retrieval_settings().retrieval_model_catalog)
        return PrivateFileRetriever(
            repository=self.repository,
            vectors=self.private_vectors,
            embedder=RemoteDenseEncoder(self._embedding_spec, client),
            reranker=RemotePassageReranker(
                catalog.get(self.settings.private_file_reranker_model), client
            ),
        )

    @cached_property
    def web_search(self) -> TavilyWebSearch | None:
        return TavilyWebSearch(self.settings) if self.settings.web_search_enabled else None

    @cached_property
    def file_ingestion(self) -> FileIngestionService:
        client = self._inference_client()
        return FileIngestionService(
            repository=self.repository,
            storage=self.storage,
            embedder=RemotePassageEmbedder(self._embedding_spec, client),
            vectors=self.private_vectors,
        )

    async def run(self) -> None:
        try:
            resumed = await self.repository.resume_file_work()
            if resumed:
                logger.info("Queued %d unfinished file jobs", resumed)
        except Exception as exc:
            logger.warning("File job resume skipped (%s)", type(exc).__name__)
        await asyncio.gather(
            self._run_lane(INTERACTIVE_JOB_KINDS, recover_stale=True),
            self._run_lane(INGEST_JOB_KINDS, recover_stale=False),
        )

    async def _run_lane(self, kinds: Sequence[str], *, recover_stale: bool) -> None:
        next_recovery = 0.0
        while not self.stopping.is_set():
            now = time.monotonic()
            if recover_stale and now >= next_recovery:
                recovered = await self.repository.recover_stale_jobs(
                    self.settings.chat_worker_stale_minutes
                )
                if recovered:
                    logger.info("Recovered %d stale jobs", recovered)
                await self._expire_abandoned_uploads()
                next_recovery = now + 60.0
            job = await self.repository.claim_job(self.worker_id, kinds)
            if job is None:
                try:
                    await asyncio.wait_for(
                        self.stopping.wait(), timeout=self.settings.chat_worker_poll_seconds
                    )
                except TimeoutError:
                    pass
                continue
            await self._process(job)

    async def _expire_abandoned_uploads(self) -> None:
        # Housekeeping must never stop the lane that answers questions.
        try:
            expired = await self.repository.expire_abandoned_uploads()
        except Exception as exc:
            logger.warning("Abandoned upload cleanup skipped (%s)", type(exc).__name__)
            return
        if expired:
            logger.info("Queued %d abandoned uploads for deletion", expired)

    async def _process(self, job: dict) -> None:
        try:
            if job["kind"] == "chat_generation":
                await self._chat(job)
            elif job["kind"] == "file_verification":
                await self._verify_file(job)
            elif job["kind"] == "file_ingest":
                await self.file_ingestion.ingest(job)
            elif job["kind"] == "file_deletion":
                await self._delete_file(job)
            else:
                raise PermanentLLMError("unsupported_job_kind")
        except TransientLLMError:
            await self.repository.fail_job(
                job, error_code="provider_temporarily_unavailable", retryable=True
            )
        except TransientInferenceError:
            await self.repository.fail_job(
                job, error_code="model_temporarily_unavailable", retryable=True
            )
        except TransientWebSearchError:
            await self.repository.fail_job(
                job, error_code="web_search_temporarily_unavailable", retryable=True
            )
        except StorageError:
            await self.repository.fail_job(
                job, error_code="storage_temporarily_unavailable", retryable=True
            )
        except VectorStoreUnavailable:
            await self.repository.fail_job(
                job, error_code="vector_store_temporarily_unavailable", retryable=True
            )
        except ConflictError:
            logger.info("Job %s was cancelled or superseded", job["id"])
            # Without this the job would sit in processing until stale recovery
            # re-ran it, only to hit the same conflict again.
            await self.repository.cancel_job(job["id"])
        except Exception as exc:
            logger.warning("Job failed safely (%s)", type(exc).__name__)
            await self.repository.fail_job(job, error_code=self._safe_error(exc), retryable=False)

    async def _chat(self, job: dict) -> None:
        work = await self.repository.get_chat_work(job["subject_id"])
        search_mode = work.get("search_mode") or "corpus"
        service = GroundedChatService(
            _load_search_coordinator(),
            get_llm_provider(),
            self.settings,
            private_retriever=self.private_retriever,
            web_search=self.web_search if search_mode == "web" else None,
            provisions=self.repository,
        )

        async def report_stage(stage: str) -> None:
            # Progress is display-only; a failed update must never fail the answer.
            try:
                await self.repository.set_generation_stage(job["subject_id"], stage)
            except Exception as exc:
                logger.warning("Stage update skipped (%s)", type(exc).__name__)

        scope = PrivateScope(
            workspace_id=work["workspace_id"],
            conversation_id=work["conversation_id"],
            case_id=work["case_id"],
        )
        if search_mode == "analysis":
            result = await CaseAnalysisService(service, self.repository, self.settings).analyze(
                domain=work["domain_code"], private_scope=scope, on_stage=report_stage
            )
            await self.repository.complete_generation(job["subject_id"], result)
            return
        if work.get("deep_research"):
            result = await DeepResearchService(service, self.settings).research(
                message=work["user_message"],
                history=work["history"],
                domain=work["domain_code"],
                private_scope=scope,
                web=search_mode == "web",
                on_stage=report_stage,
            )
            await self.repository.complete_generation(job["subject_id"], result)
            return
        result = await service.answer(
            message=work["user_message"],
            retrieval_query=work["retrieval_query"],
            domain=work["domain_code"],
            history=work["history"],
            on_stage=report_stage,
            private_scope=scope,
            search_mode=search_mode,
            amended_checks=work.get("amended_checks") or [],
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
        # Vectors first: once they are gone nothing can surface this file's text.
        await asyncio.to_thread(
            self.private_vectors.delete_file,
            workspace_id=file["workspace_id"],
            file_id=file["id"],
        )
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
                    "output_truncated",
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
        if isinstance(exc, WebSearchError):
            return str(exc) if str(exc) in SAFE_WEB_SEARCH_ERRORS else "web_search_failed"
        # ExtractionError is a ValueError whose message is always a safe code.
        if isinstance(exc, ValueError) and str(exc) in _SAFE_FILE_ERRORS:
            return str(exc)
        return "job_failed"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # HTTP client INFO records contain private Storage paths and request URLs.
    for name in ("httpx", "httpcore", "google_genai", "google.genai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # pypdf reports every malformed object it recovers from; none of it is actionable.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    worker = Worker()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, worker.stopping.set)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
