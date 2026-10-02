from __future__ import annotations

from functools import lru_cache
from typing import Literal
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
    # Rewrites follow-up questions into standalone search queries; small and fast.
    gemini_query_model: str = "gemini-3.5-flash-lite"
    # Case analysis: finds a case's legal issues and writes the report. A separate model
    # also keeps its free-tier quota apart from the chat's primary model.
    gemini_analysis_model: str = "gemini-3.6-flash"
    # Deep research: plans the parts of a question, finds what is missing after the first
    # search round and writes the report. Its own model keeps its quota apart as well.
    gemini_research_model: str = "gemini-3.7-flash"
    # Evidence budget per answer. Retrieval rarely fills it; it is a ceiling, not a target
    # to reach. Gemini Flash accepts far more, the free tier allows 250K input tokens/min.
    gemini_target_input_tokens: int = Field(default=96_000, ge=8_000, le=192_000)
    gemini_max_input_tokens: int = Field(default=160_000, ge=16_000, le=192_000)
    # Thinking tokens count against this budget too; "high" thinking needs the headroom.
    gemini_max_output_tokens: int = Field(default=16_384, ge=512, le=32_768)
    # Deeper reasoning for the answer (primary model only; the fallback keeps its default).
    gemini_answer_thinking_level: Literal["minimal", "low", "medium", "high"] | None = "high"
    # Verification is classification: the same pair should always get the same verdict.
    # None keeps the model's default (used by the evaluation's "before" variant).
    gemini_verifier_temperature: float | None = Field(default=0.0, ge=0.0, le=2.0)
    gemini_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    # Web search, offered only when the corpus has no source. Tavily's free plan has
    # 1,000 credits a month (basic search 1, advanced 2). Without a key it stays hidden.
    tavily_api_key: SecretStr | None = None
    web_search_depth: Literal["basic", "advanced"] = "advanced"
    web_search_max_results: int = Field(default=8, ge=1, le=20)
    web_search_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    chat_worker_poll_seconds: float = Field(default=2.0, ge=0.25, le=30)
    chat_worker_stale_minutes: int = Field(default=10, ge=2, le=120)
    chat_max_active_jobs: int = Field(default=2, ge=1, le=10)
    case_files_bucket: str = "case-files"
    case_file_max_bytes: int = 52_428_800
    user_file_quota_bytes: int = 104_857_600
    # Must match the dense model of the global index so one query vector serves both.
    private_file_embedding_model: str = "bge-m3"
    private_file_reranker_model: str = "bge-reranker-v2-m3"

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

    @property
    def web_search_enabled(self) -> bool:
        return bool(self.tavily_api_key and self.tavily_api_key.get_secret_value().strip())

    @property
    def tavily_secret(self) -> str:
        if not self.web_search_enabled:
            raise ValueError("TAVILY_API_KEY is required")
        return self.tavily_api_key.get_secret_value().strip()  # type: ignore[union-attr]


@lru_cache
def get_settings() -> Settings:
    return Settings()
