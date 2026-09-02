from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RetrievalSettings(BaseSettings):
    database_url: str = "postgresql://beken:local-development-only@localhost:5432/beken"
    supabase_db_url: SecretStr | None = None
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    retrieval_index_root: Path = Path("retrieval_data")
    retrieval_scope_root: Path = Path("retrieval-scopes")
    retrieval_model_catalog: Path = Path("retrieval/config/models.json")
    retrieval_profile_catalog: Path = Path("retrieval/config/domain_profiles.json")
    model_inference_url: str | None = None
    model_inference_token: SecretStr | None = None
    model_inference_timeout_seconds: float = 120.0

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def corpus_database_url(self) -> str:
        if not self.supabase_db_url:
            return self.database_url
        url = self.supabase_db_url.get_secret_value()
        parts = urlsplit(url)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() != "sslmode"
        ]
        query.append(("sslmode", "require"))
        return urlunsplit(parts._replace(query=urlencode(query)))

    @property
    def qdrant_secret(self) -> str | None:
        return self.qdrant_api_key.get_secret_value() if self.qdrant_api_key else None

    @property
    def model_inference_base_url(self) -> str:
        if not self.model_inference_url:
            raise ValueError("MODEL_INFERENCE_URL is required for runtime retrieval")
        parts = urlsplit(self.model_inference_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("MODEL_INFERENCE_URL must be an absolute HTTP(S) URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("MODEL_INFERENCE_URL cannot contain credentials, query, or fragment")
        if parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Plain HTTP model inference is allowed only over loopback")
        return self.model_inference_url.rstrip("/")

    @property
    def model_inference_secret(self) -> str:
        if not self.model_inference_token:
            raise ValueError("MODEL_INFERENCE_TOKEN is required for runtime retrieval")
        value = self.model_inference_token.get_secret_value()
        if len(value) < 32:
            raise ValueError("MODEL_INFERENCE_TOKEN must contain at least 32 characters")
        return value


@lru_cache
def get_settings() -> RetrievalSettings:
    return RetrievalSettings()
