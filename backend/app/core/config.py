from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Beken.ai API"
    app_version: str = "0.1.0"
    environment: str = "development"
    database_url: str = "postgresql://beken:local-development-only@localhost:5432/beken"
    supabase_db_url: SecretStr | None = None
    supabase_db_ssl_root_cert: str | None = None
    supabase_url: str | None = None
    supabase_publishable_key: SecretStr | None = None
    supabase_secret_key: SecretStr | None = None
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    cors_origins: str = "http://localhost:3000"
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    llm_provider: str = "disabled"
    gemini_api_key: SecretStr | None = None
    gemini_primary_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    gemini_claim_support_model: str = "gemini-3.5-flash-lite"
    gemini_target_input_tokens: int = Field(default=64_000, ge=8_000, le=128_000)
    gemini_max_input_tokens: int = Field(default=128_000, ge=16_000, le=128_000)
    gemini_max_output_tokens: int = Field(default=4_096, ge=512, le=4_096)
    gemini_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    chat_worker_poll_seconds: float = Field(default=2.0, ge=0.25, le=30)
    chat_worker_stale_minutes: int = Field(default=10, ge=2, le=120)
    chat_max_active_jobs: int = Field(default=2, ge=1, le=10)
    case_files_bucket: str = "case-files"
    case_file_max_bytes: int = 52_428_800
    user_file_quota_bytes: int = 104_857_600

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_context_budget(self) -> Settings:
        if self.gemini_target_input_tokens > self.gemini_max_input_tokens:
            raise ValueError("GEMINI_TARGET_INPUT_TOKENS cannot exceed the hard input limit")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def app_database_url(self) -> str:
        if not self.supabase_db_url:
            return self.database_url
        url = self.supabase_db_url.get_secret_value()
        parts = urlsplit(url)
        replaced_keys = {"sslmode"}
        if self.supabase_db_ssl_root_cert:
            replaced_keys.add("sslrootcert")
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in replaced_keys
        ]
        if self.supabase_db_ssl_root_cert:
            query.append(("sslrootcert", self.supabase_db_ssl_root_cert))
        query.append(("sslmode", "verify-full"))
        return urlunsplit(parts._replace(query=urlencode(query)))

    @property
    def supabase_publishable_secret(self) -> str:
        if not self.supabase_publishable_key:
            raise ValueError("SUPABASE_PUBLISHABLE_KEY is required")
        return self.supabase_publishable_key.get_secret_value()

    @property
    def supabase_backend_secret(self) -> str:
        if not self.supabase_secret_key:
            raise ValueError("SUPABASE_SECRET_KEY is required")
        return self.supabase_secret_key.get_secret_value()

    @property
    def gemini_secret(self) -> str:
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required")
        return self.gemini_api_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
