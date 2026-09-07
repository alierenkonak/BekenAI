import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
