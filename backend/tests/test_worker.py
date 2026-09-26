import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beken_retrieval.remote_inference import TransientInferenceError

from app import worker as worker_module


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
    await worker.run()
    assert worker.repository.recover_stale_jobs.await_count == 2


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
    def __init__(self, *_args) -> None:
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
    worker.repository = SimpleNamespace(
        get_chat_work=AsyncMock(
            return_value={
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
