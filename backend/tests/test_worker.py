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
