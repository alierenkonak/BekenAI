import os
from pathlib import Path

import psycopg
import pytest

from beken_ingestion.config import IngestionSettings
from beken_ingestion.database import CorpusRepository
from beken_ingestion.models import RawDocument
from beken_ingestion.normalization import stable_hash
from beken_ingestion.pipeline import IngestionPipeline
from beken_ingestion.storage import FilesystemRawStorage

pytestmark = pytest.mark.skipif(
    os.getenv("BEKEN_RUN_DB_TESTS") != "1",
    reason="requires the local migrated PostgreSQL service",
)


def _database_url() -> str:
    return IngestionSettings().database_url


def test_repeated_import_is_idempotent_and_chunks_trace_to_document(tmp_path: Path) -> None:
    database_url = _database_url()
    repository = CorpusRepository(database_url)
    pipeline = IngestionPipeline(repository, FilesystemRawStorage(tmp_path))
    raw = RawDocument(
        source_name="manual",
        source_document_id="integration-idempotency-fixture",
        source_url="file:///integration-idempotency-fixture.txt",
        media_type="text/plain",
        content=(
            "GEREKÇE\nFeshin geçerli nedene dayanıp dayanmadığı değerlendirilmiştir.\n\n"
            "HÜKÜM\nDosyanın sonucuna göre karar verilmiştir."
        ).encode(),
        metadata={
            "source_kind": "court_decision",
            "document_type": "court_decision",
            "domain": "labour_law",
            "authority": "Yargıtay",
            "chamber": "9. Hukuk Dairesi",
            "case_number": "2099/1",
            "decision_number": "2099/2",
            "document_date": "2099-01-01",
        },
    )

    first = pipeline.ingest(raw)
    second = pipeline.ingest(raw)
    try:
        assert first.duplicate_document is False
        assert second.duplicate_document is True
        assert second.duplicate_artifact is True
        assert first.document_id == second.document_id
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from legal.document_chunks where document_id = %s",
                (first.document_id,),
            )
            assert cursor.fetchone()[0] == first.chunk_count
            catalog_row = cursor.execute(
                """
                select display_name, legal_identifier, document_category
                from legal.document_catalog
                where document_id = %s
                """,
                (first.document_id,),
            ).fetchone()
            assert catalog_row == (
                "Yargıtay 9. Hukuk Dairesi, E. 2099/1, K. 2099/2",
                "E. 2099/1 / K. 2099/2",
                "İçtihat Kararı",
            )
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("delete from legal.documents where id = %s", (first.document_id,))


def test_corpus_versions_pin_parses_and_failed_repin_rolls_back(tmp_path: Path) -> None:
    database_url = _database_url()
    repository = CorpusRepository(database_url)
    pipeline = IngestionPipeline(repository, FilesystemRawStorage(tmp_path))
    first_version = "integration-parser-v1"
    second_version = "integration-parser-v2"
    repository.upsert_corpus_version(
        first_version, stable_hash(b"integration-v1"), {"version": first_version}
    )
    repository.upsert_corpus_version(
        second_version, stable_hash(b"integration-v2"), {"version": second_version}
    )
    metadata = {
        "source_kind": "legislation",
        "document_type": "law",
        "domain": "labour_law",
        "title": "Integration Test Kanunu",
    }
    first_raw = RawDocument(
        source_name="manual",
        source_document_id="integration-versioned-parser",
        source_url="file:///integration-versioned-parser-v1.txt",
        media_type="text/plain",
        content=b"MADDE 1 - Birinci metin yeterli uzunlukta bir hukuki hukum icerir.",
        metadata=metadata,
    )
    second_raw = RawDocument(
        source_name="manual",
        source_document_id="integration-versioned-parser",
        source_url="file:///integration-versioned-parser-v2.txt",
        media_type="text/plain",
        content=b"MADDE 1 - Ikinci metin farkli ve yeterli uzunlukta bir hukuki hukum icerir.",
        metadata=metadata,
    )

    first = pipeline.ingest(first_raw, first_version)
    try:
        with pytest.raises(ValueError, match="already pins a different parse"):
            pipeline.ingest(second_raw, first_version)

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            current_after_failure = cursor.execute(
                "select current_parse_id from legal.documents where id = %s",
                (first.document_id,),
            ).fetchone()[0]
            parse_count_after_failure = cursor.execute(
                "select count(*) from legal.document_parses where document_id = %s",
                (first.document_id,),
            ).fetchone()[0]
        assert str(current_after_failure) == first.parse_id
        assert parse_count_after_failure == 1

        second = pipeline.ingest(second_raw, second_version)
        assert second.parse_id != first.parse_id
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            pinned = cursor.execute(
                """
                select corpus_version, parse_id
                from legal.corpus_version_documents
                where document_id = %s
                order by corpus_version
                """,
                (first.document_id,),
            ).fetchall()
        assert [(row[0], str(row[1])) for row in pinned] == [
            (first_version, first.parse_id),
            (second_version, second.parse_id),
        ]
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "delete from legal.corpus_versions where version in (%s, %s)",
                (first_version, second_version),
            )
            cursor.execute("delete from legal.documents where id = %s", (first.document_id,))


def test_same_artifact_can_join_two_domains_without_duplication(tmp_path: Path) -> None:
    database_url = _database_url()
    repository = CorpusRepository(database_url)
    pipeline = IngestionPipeline(repository, FilesystemRawStorage(tmp_path))
    raw_content = b"MADDE 1 - Ortak kanun metni yeterli uzunlukta bir hukum icerir."
    base_metadata = {
        "source_kind": "legislation",
        "document_type": "law",
        "domain": "labour_law",
        "title": "Ortak Integration Kanunu",
        "domain_metadata": {"corpus_role": "supplemental"},
    }
    labour_raw = RawDocument(
        source_name="manual",
        source_document_id="integration-shared-law",
        source_url="file:///integration-shared-law.txt",
        media_type="text/plain",
        content=raw_content,
        metadata=base_metadata,
    )
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            insert into legal.domains (code, display_name, status)
            values ('tax_law', 'Vergi Hukuku', 'experimental')
            on conflict (code) do nothing
            """
        )

    first = pipeline.ingest(labour_raw)
    tax_raw = RawDocument(
        source_name=labour_raw.source_name,
        source_document_id=labour_raw.source_document_id,
        source_url=labour_raw.source_url,
        media_type=labour_raw.media_type,
        content=labour_raw.content,
        metadata={
            **base_metadata,
            "domain": "tax_law",
            "domain_metadata": {"corpus_role": "core", "tax_topic": "fixture"},
        },
    )
    second = pipeline.ingest(tax_raw)
    try:
        assert second.document_id == first.document_id
        assert second.artifact_id == first.artifact_id
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            counts = cursor.execute(
                """
                select
                  (select count(*) from legal.documents where id = %s),
                  (select count(*) from legal.document_artifacts where document_id = %s),
                  (select count(*) from legal.document_domains where document_id = %s)
                """,
                (first.document_id, first.document_id, first.document_id),
            ).fetchone()
            domains = cursor.execute(
                """
                select domain_code, role
                from legal.document_domains
                where document_id = %s
                order by domain_code
                """,
                (first.document_id,),
            ).fetchall()
        assert counts == (1, 1, 2)
        assert domains == [("labour_law", "supplemental"), ("tax_law", "core")]
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("delete from legal.documents where id = %s", (first.document_id,))
            cursor.execute("delete from legal.domains where code = 'tax_law'")


def test_domain_registry_tables_are_private_and_rls_enabled() -> None:
    database_url = _database_url()
    table_names = (
        "domains",
        "source_kinds",
        "document_types",
        "legal_unit_types",
        "document_domains",
        "corpus_version_domains",
        "retrieval_scopes",
        "retrieval_indexes",
    )
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        rows = cursor.execute(
            """
            select c.relname, c.relrowsecurity
            from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'legal' and c.relname = any(%s)
            order by c.relname
            """,
            (list(table_names),),
        ).fetchall()
        public_grants = cursor.execute(
            """
            select count(*)
            from information_schema.role_table_grants
            where table_schema = 'legal'
              and table_name = any(%s)
              and grantee in ('PUBLIC', 'anon', 'authenticated')
            """,
            (list(table_names),),
        ).fetchone()[0]

    assert {row[0] for row in rows} == set(table_names)
    assert all(row[1] for row in rows)
    assert public_grants == 0
