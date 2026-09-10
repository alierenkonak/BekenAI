from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    database_url: str = "postgresql://beken:local-development-only@localhost:5432/beken"
    supabase_url: str | None = None
    supabase_db_url: SecretStr | None = None
    supabase_db_ssl_root_cert: str | None = None
    supabase_publishable_key: str | None = None
    supabase_secret_key: SecretStr | None = None
    supabase_storage_bucket: str = "legal-raw"
    local_raw_storage_path: Path = Path("raw_data")
    source_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    source_rate_limit_seconds: float = Field(default=1.0, ge=0.5, le=30)
    source_max_attempts: int = Field(default=3, ge=1, le=5)

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url(cls, value: str | None) -> str | None:
        if value and not value.startswith("https://"):
            raise ValueError("SUPABASE_URL must use HTTPS")
        return value.rstrip("/") if value else None

    def require_supabase(self) -> tuple[str, str]:
        if not self.supabase_url or not self.supabase_secret_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY are required")
        return self.supabase_url, self.supabase_secret_key.get_secret_value()

    @property
    def metadata_database_url(self) -> str:
        if self.supabase_db_url:
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
        return self.database_url


@lru_cache
def get_settings() -> IngestionSettings:
    return IngestionSettings()
