from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from beken_retrieval.config import RetrievalSettings
from beken_retrieval.postgres import PostgresCorpusRepository
from beken_retrieval.scope import RetrievalScope

pytestmark = pytest.mark.skipif(
    os.getenv("BEKEN_RUN_DB_TESTS") != "1",
    reason="requires the local migrated PostgreSQL service",
)


def _scope(manifest_hash: str, review_status: str) -> RetrievalScope:
    payload = {
        "version": "integration-retrieval-scope-v1",
        "domain": "labour_law",
        "corpus_version": "integration-retrieval-corpus-v1",
        "review_status": review_status,
        "roles": {"core": {"include": True, "mode": "full_document"}},
    }
    return RetrievalScope(
        path=Path("integration-scope.json"),
        payload=payload,
        manifest_hash=manifest_hash,
    )


def test_draft_scope_can_be_reviewed_then_becomes_immutable() -> None:
    database_url = RetrievalSettings().database_url
    repository = PostgresCorpusRepository(database_url)
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            insert into legal.corpus_versions (version, manifest_hash, manifest, status)
            values (%s, %s, '{}'::jsonb, 'draft')
            on conflict (version) do nothing
            """,
            ("integration-retrieval-corpus-v1", "1" * 64),
        )
    try:
        repository.register_scope(_scope("a" * 64, "pending_user_review"))
        repository.register_scope(_scope("b" * 64, "reviewed"))

        with psycopg.connect(database_url) as connection:
            row = connection.execute(
                """
                select manifest_hash, status, reviewed_at is not null
                from legal.retrieval_scopes
                where version = %s
                """,
                ("integration-retrieval-scope-v1",),
            ).fetchone()
        assert row == ("b" * 64, "reviewed", True)

        with pytest.raises(ValueError, match="different manifest"):
            repository.register_scope(_scope("c" * 64, "reviewed"))
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "delete from legal.retrieval_indexes where scope_version = %s",
                ("integration-retrieval-scope-v1",),
            )
            connection.execute(
                "delete from legal.retrieval_scopes where version = %s",
                ("integration-retrieval-scope-v1",),
            )
            connection.execute(
                "delete from legal.corpus_versions where version = %s",
                ("integration-retrieval-corpus-v1",),
            )


def test_activating_new_backend_index_retires_previous_version() -> None:
    database_url = RetrievalSettings().database_url
    repository = PostgresCorpusRepository(database_url)
    scope = _scope("d" * 64, "reviewed")
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            insert into legal.corpus_versions (version, manifest_hash, manifest, status)
            values (%s, %s, '{}'::jsonb, 'draft')
            on conflict (version) do nothing
            """,
            ("integration-retrieval-corpus-v1", "1" * 64),
        )
    try:
        repository.register_scope(scope)
        first = repository.register_index(
            scope=scope,
            backend="bm25s",
            model_id="bm25s",
            model_revision="fixture",
            index_version="fixture-one",
            manifest={"version": "one"},
        )
        second = repository.register_index(
            scope=scope,
            backend="bm25s",
            model_id="bm25s",
            model_revision="fixture",
            index_version="fixture-two",
            manifest={"version": "two"},
        )

        with psycopg.connect(database_url) as connection:
            rows = connection.execute(
                """
                select id::text, status
                from legal.retrieval_indexes
                where scope_version = %s
                order by index_version
                """,
                (scope.version,),
            ).fetchall()
        assert rows == [(first, "retired"), (second, "ready")]

        repository.activate_index(
            domain=scope.domain,
            backend="bm25s",
            index_version="fixture-one",
        )
        with psycopg.connect(database_url) as connection:
            rows = connection.execute(
                """
                select id::text, status
                from legal.retrieval_indexes
                where scope_version = %s
                order by index_version
                """,
                (scope.version,),
            ).fetchall()
        assert rows == [(first, "ready"), (second, "retired")]
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "delete from legal.retrieval_indexes where scope_version = %s",
                (scope.version,),
            )
            connection.execute(
                "delete from legal.retrieval_scopes where version = %s",
                (scope.version,),
            )
            connection.execute(
                "delete from legal.corpus_versions where version = %s",
                (scope.corpus_version,),
            )
