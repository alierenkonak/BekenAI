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
