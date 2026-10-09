from __future__ import annotations

from functools import lru_cache

import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings


class AppDatabase:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def connect(self, *, autocommit: bool = False) -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
            connect_timeout=10,
            prepare_threshold=None,
            autocommit=autocommit,
        )


@lru_cache
def get_database() -> AppDatabase:
    return AppDatabase(get_settings().app_database_url)
