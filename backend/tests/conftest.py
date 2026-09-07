"""Backend unit tests never use developer indexes, credentials, or real sockets."""

import os
import socket
from uuid import UUID

import pytest
from beken_retrieval.config import RetrievalSettings
from beken_retrieval.coordinator import DomainSearchCoordinator, InMemoryIndexRegistry

from app.api import search as search_api
from app.core.auth import AuthenticatedUser, get_current_user
from app.main import app


@pytest.fixture(autouse=True)
def isolated_backend(monkeypatch, tmp_path):
    def deny_network(*args, **kwargs):
        raise RuntimeError("Network access is disabled in backend unit tests")

    # The explicit DB integration suite must reach the local Docker PostgreSQL
    # service. Normal unit tests remain hermetic and cannot open any socket.
    if os.getenv("BEKEN_RUN_DB_TESTS") != "1":
        for name in ("create_connection", "getaddrinfo"):
            monkeypatch.setattr(socket, name, deny_network)
        for name in ("connect", "connect_ex"):
            monkeypatch.setattr(socket.socket, name, deny_network)
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_TOKEN_PATH", str(tmp_path / "hf" / "token"))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    monkeypatch.setattr(
        search_api,
        "get_retrieval_settings",
        lambda: RetrievalSettings(
            _env_file=None,
            retrieval_index_root=tmp_path / "indexes",
            database_url="postgresql://unused:unused@localhost/unused",
            supabase_db_url=None,
            qdrant_url="http://localhost:6333",
            qdrant_api_key=None,
        ),
    )
    previous = app.dependency_overrides.copy()
    search_api._load_search_coordinator.cache_clear()
    app.dependency_overrides[search_api.get_search_coordinator] = lambda: DomainSearchCoordinator(
        InMemoryIndexRegistry()
    )
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="user@example.test",
    )
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        search_api._load_search_coordinator.cache_clear()
