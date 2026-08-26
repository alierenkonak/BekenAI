from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Beken.ai API"
    app_version: str = "0.1.0"
    environment: str = "development"
    database_url: str = "postgresql://beken:local-development-only@localhost:5432/beken"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    cors_origins: str = "http://localhost:3000"
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

