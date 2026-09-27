import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beken_retrieval.remote_inference import TransientInferenceError

from app import worker as worker_module
from app.core.repository import ConflictError
from app.files.extraction import ExtractionError
from app.files.vectors import VectorStoreUnavailable


@pytest.mark.asyncio
async def test_worker_recovers_jobs_that_become_stale_after_start(monkeypatch):
    worker = worker_module.Worker.__new__(worker_module.Worker)
    worker.settings = SimpleNamespace(chat_worker_stale_minutes=10)
    worker.stopping = asyncio.Event()
    worker.worker_id = "test-worker"
    worker.repository = SimpleNamespace(
        recover_stale_jobs=AsyncMock(return_value=1),
        claim_job=AsyncMock(return_value={"id": "fixture"}),
    )
    clock = iter((1.0, 62.0))
    monkeypatch.setattr(worker_module, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    calls = 0

    async def process(job):
        nonlocal calls
        calls += 1
        if calls == 2:
            worker.stopping.set()

    worker._process = process
    await worker._run_lane(worker_module.INTERACTIVE_JOB_KINDS, recover_stale=True)
    assert worker.repository.recover_stale_jobs.await_count == 2
    worker.repository.claim_job.assert_awaited_with(
        "test-worker", worker_module.INTERACTIVE_JOB_KINDS
    )


@pytest.mark.asyncio
async def test_worker_runs_a_separate_ingest_lane_after_resuming_file_work():
    worker = worker_module.Worker.__new__(worker_module.Worker)
    worker.settings = SimpleNamespace(chat_worker_stale_minutes=10, chat_worker_poll_seconds=0.01)
    worker.stopping = asyncio.Event()
    worker.worker_id = "test-worker"
    claimed: list[tuple[str, ...]] = []

    async def claim_job(worker_id, kinds):
        claimed.append(tuple(kinds))
        if len(claimed) >= 2:
            worker.stopping.set()
        return None

    worker.repository = SimpleNamespace(
        resume_file_work=AsyncMock(return_value=0),
        recover_stale_jobs=AsyncMock(return_value=0),
        claim_job=claim_job,
    )

    await worker.run()

    worker.repository.resume_file_work.assert_awaited_once()
    assert set(claimed) == {
        worker_module.INTERACTIVE_JOB_KINDS,
        worker_module.INGEST_JOB_KINDS,
    }
    # Only the interactive lane recovers stale jobs, so recovery never races itself.
    assert worker.repository.recover_stale_jobs.await_count == 1


def _file_worker(**repository) -> worker_module.Worker:
    worker = worker_module.Worker.__new__(worker_module.Worker)
    worker.repository = SimpleNamespace(
        fail_job=AsyncMock(), cancel_job=AsyncMock(), **repository
    )
    return worker


@pytest.mark.asyncio
async def test_ingest_jobs_go_to_the_ingestion_service():
    worker = _file_worker()
    worker.file_ingestion = SimpleNamespace(ingest=AsyncMock())
    job = {"id": "job-id", "kind": "file_ingest", "attempt_count": 1}

    await worker._process(job)

    worker.file_ingestion.ingest.assert_awaited_once_with(job)
    worker.repository.fail_job.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (ExtractionError("scanned_pdf_not_supported"), "scanned_pdf_not_supported", False),
        (ExtractionError("encrypted_pdf"), "encrypted_pdf", False),
        (VectorStoreUnavailable("down"), "vector_store_temporarily_unavailable", True),
        (TransientInferenceError("busy"), "model_temporarily_unavailable", True),
        (RuntimeError("secret detail"), "job_failed", False),
    ],
)
async def test_ingest_failures_map_to_safe_codes(error, code, retryable):
    worker = _file_worker()
    worker.file_ingestion = SimpleNamespace(ingest=AsyncMock(side_effect=error))
    job = {"id": "job-id", "kind": "file_ingest", "attempt_count": 1}

    await worker._process(job)

    worker.repository.fail_job.assert_awaited_once_with(
        job, error_code=code, retryable=retryable
    )


@pytest.mark.asyncio
async def test_superseded_jobs_are_closed_instead_of_left_processing():
    worker = _file_worker()
    worker.file_ingestion = SimpleNamespace(
        ingest=AsyncMock(side_effect=ConflictError("file_not_indexing"))
    )

    await worker._process({"id": "job-id", "kind": "file_ingest", "attempt_count": 1})

    worker.repository.cancel_job.assert_awaited_once_with("job-id")
    worker.repository.fail_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_file_deletion_removes_vectors_before_the_stored_object():
    order: list[str] = []
    file = {
        "id": "file-id",
        "workspace_id": "workspace-id",
        "storage_path": "user/workspace/case/file-id/dilekce.pdf",
    }
    worker = _file_worker(
        get_worker_file=AsyncMock(return_value=file),
        complete_file_deletion=AsyncMock(side_effect=lambda *_: order.append("row")),
    )
    deleted_vectors: list[dict] = []

    def delete_vectors(**scope):
        deleted_vectors.append(scope)
        order.append("vectors")

    worker.private_vectors = SimpleNamespace(delete_file=delete_vectors)
    worker.storage = SimpleNamespace(
        delete=AsyncMock(side_effect=lambda *_: order.append("object"))
    )

    await worker._delete_file({"id": "job-id", "subject_id": "file-id"})

    assert deleted_vectors == [{"workspace_id": "workspace-id", "file_id": "file-id"}]
    assert order == ["vectors", "object", "row"]


@pytest.mark.asyncio
async def test_file_verification_bounds_download_to_declared_size():
    worker = worker_module.Worker.__new__(worker_module.Worker)
    worker.storage = SimpleNamespace(download=AsyncMock(return_value=b"%PDF-1.7\n"))
    worker.repository = SimpleNamespace(
        get_worker_file=AsyncMock(
            return_value={
                "id": "file-id",
                "storage_path": "private/file.pdf",
                "expected_size_bytes": 9,
                "declared_media_type": "application/pdf",
            }
        ),
        complete_file_verification=AsyncMock(),
    )

    await worker._verify_file({"id": "job-id", "subject_id": "file-id"})

    worker.storage.download.assert_awaited_once_with(
        "private/file.pdf", maximum_bytes=9
    )
    worker.repository.complete_file_verification.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_retries_transient_model_service_failure():
    worker = worker_module.Worker.__new__(worker_module.Worker)
    worker.repository = SimpleNamespace(fail_job=AsyncMock())
    worker._chat = AsyncMock(side_effect=TransientInferenceError("unavailable"))
    job = {"id": "job-id", "kind": "chat_generation", "attempt_count": 1}

    await worker._process(job)

    worker.repository.fail_job.assert_awaited_once_with(
        job, error_code="model_temporarily_unavailable", retryable=True
    )


class _StageReportingService:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def answer(self, *, on_stage, **_kwargs):
        for stage in ("retrieving", "generating", "verifying"):
            await on_stage(stage)
        return SimpleNamespace(answer_status="answered")


def _chat_worker(monkeypatch, set_generation_stage: AsyncMock) -> worker_module.Worker:
    monkeypatch.setattr(worker_module, "GroundedChatService", _StageReportingService)
    monkeypatch.setattr(worker_module, "_load_search_coordinator", lambda: None)
    monkeypatch.setattr(worker_module, "get_llm_provider", lambda: None)
    worker = worker_module.Worker.__new__(worker_module.Worker)
    worker.settings = SimpleNamespace()
    worker.private_retriever = None
    worker.repository = SimpleNamespace(
        get_chat_work=AsyncMock(
            return_value={
                "workspace_id": "workspace-id",
                "conversation_id": "conversation-id",
                "case_id": None,
                "user_message": "Fesih nasıl yapılır?",
                "retrieval_query": "fesih nasıl yapılır",
                "domain_code": "labour_law",
                "include_doctrine": False,
                "history": [],
            }
        ),
        set_generation_stage=set_generation_stage,
        complete_generation=AsyncMock(),
    )
    return worker


@pytest.mark.asyncio
async def test_chat_job_persists_each_pipeline_stage(monkeypatch):
    set_stage = AsyncMock()
    worker = _chat_worker(monkeypatch, set_stage)

    await worker._chat({"id": "job-id", "subject_id": "generation-id"})

    assert [call.args for call in set_stage.await_args_list] == [
        ("generation-id", "retrieving"),
        ("generation-id", "generating"),
        ("generation-id", "verifying"),
    ]
    worker.repository.complete_generation.assert_awaited_once()


@pytest.mark.asyncio
async def test_stage_update_failure_does_not_fail_the_answer(monkeypatch):
    worker = _chat_worker(monkeypatch, AsyncMock(side_effect=RuntimeError("db hiccup")))

    await worker._chat({"id": "job-id", "subject_id": "generation-id"})

    worker.repository.complete_generation.assert_awaited_once()
