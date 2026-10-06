from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.config import get_settings
from app.core.repository import Page, get_repository
from app.main import app


class _Repository:
    def __init__(self) -> None:
        self.lists: list[dict] = []
        self.updates: list[dict] = []

    async def list_conversations(self, user_id, **options):
        self.lists.append(options)
        return Page(items=[], next_cursor=None)

    async def update_conversation(self, user_id, conversation_id, **changes):
        self.updates.append(changes)
        return {"id": str(conversation_id), "pinned_at": "2026-10-07T10:00:00+00:00"}

    async def file_storage_bytes(self, user_id):
        return 2_048


def _client(repository: _Repository) -> httpx.AsyncClient:
    app.dependency_overrides[get_repository] = lambda: repository
    settings = SimpleNamespace(user_file_quota_bytes=104_857_600)
    app.dependency_overrides[get_settings] = lambda: settings
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_the_sidebar_lists_pinned_and_other_chats_apart() -> None:
    repository = _Repository()
    async with _client(repository) as client:
        assert (await client.get("/conversations", params={"pinned": "true"})).status_code == 200
        assert (await client.get("/conversations", params={"pinned": "false"})).status_code == 200
        assert (await client.get("/conversations")).status_code == 200

    assert [options["pinned"] for options in repository.lists] == [True, False, None]


@pytest.mark.asyncio
async def test_pinning_is_passed_on_without_touching_the_title_or_case() -> None:
    repository = _Repository()
    async with _client(repository) as client:
        response = await client.patch(f"/conversations/{uuid4()}", json={"pinned": True})

    assert response.status_code == 200
    [changes] = repository.updates
    assert changes == {"title": None, "case_id": None, "case_id_set": False, "pinned": True}


@pytest.mark.asyncio
async def test_storage_reports_usage_against_the_quota() -> None:
    async with _client(_Repository()) as client:
        response = await client.get("/me/storage")

    assert response.status_code == 200
    assert response.json() == {"used_bytes": 2_048, "quota_bytes": 104_857_600}
