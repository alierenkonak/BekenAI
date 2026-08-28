from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from beken_ingestion.models import IngestionOutcome, ParsedDocument, RawDocument


class CorpusRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def upsert_corpus_version(
        self, version: str, manifest_hash: str, manifest: dict[str, Any]
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            existing = cursor.execute(
                "select manifest_hash from legal.corpus_versions where version = %s",
                (version,),
            ).fetchone()
            if existing:
                if existing["manifest_hash"] != manifest_hash:
                    raise ValueError(f"Corpus version {version!r} already has a different manifest")
                return
            cursor.execute(
                """
                insert into legal.corpus_versions (version, manifest_hash, manifest)
                values (%s, %s, %s)
                """,
                (version, manifest_hash, Jsonb(manifest)),
            )

    def start_run(self, adapter_name: str, corpus_version: str | None) -> str:
        with self._connect() as connection, connection.cursor() as cursor:
            row = cursor.execute(
                """
                insert into legal.ingestion_runs (adapter_name, corpus_version, status)
                values (%s, %s, 'running')
                returning id
                """,
                (adapter_name, corpus_version),
            ).fetchone()
            return str(row["id"])

    def checkpoint_run(
        self,
        run_id: str,
        checkpoint: dict[str, Any],
        *,
        discovered_delta: int = 0,
        imported_delta: int = 0,
        duplicate_delta: int = 0,
        failed_delta: int = 0,
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                update legal.ingestion_runs
                set checkpoint = %s,
                    discovered_count = discovered_count + %s,
                    imported_count = imported_count + %s,
                    duplicate_count = duplicate_count + %s,
                    failed_count = failed_count + %s
                where id = %s
                """,
                (
                    Jsonb(checkpoint),
                    discovered_delta,
                    imported_delta,
                    duplicate_delta,
                    failed_delta,
                    UUID(run_id),
                ),
            )

    def get_checkpoint(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            row = cursor.execute(
                "select checkpoint from legal.ingestion_runs where id = %s",
                (UUID(run_id),),
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown ingestion run: {run_id}")
            return dict(row["checkpoint"])

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        if status not in {"completed", "failed", "blocked"}:
            raise ValueError("Invalid terminal ingestion status")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                update legal.ingestion_runs
                set status = %s, error_code = %s, error_detail = %s, finished_at = %s
                where id = %s
                """,
                (status, error_code, error_detail, datetime.now(UTC), UUID(run_id)),
            )

    def record_error(
        self,
        run_id: str,
        raw: RawDocument | None,
        error_code: str,
        error_detail: str,
        *,
        retryable: bool,
        attempt: int,
        source_url: str | None = None,
        source_document_id: str | None = None,
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                insert into legal.ingestion_errors (
                  run_id, source_url, source_document_id, error_code, error_detail,
                  retryable, attempt
                ) values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    UUID(run_id),
                    raw.source_url if raw else source_url,
                    raw.source_document_id if raw else source_document_id,
                    error_code,
                    error_detail[:2_000],
                    retryable,
                    attempt,
                ),
            )

    def persist_document(
        self,
        raw: RawDocument,
        parsed: ParsedDocument,
        *,
        raw_hash: str,
        storage_path: str,
        corpus_version: str | None,
    ) -> IngestionOutcome:
        with self._connect() as connection, connection.cursor() as cursor:
            artifact = cursor.execute(
                """
                select id, document_id from legal.document_artifacts where content_hash = %s
                """,
                (raw_hash,),
            ).fetchone()
            duplicate_artifact = artifact is not None
            document = (
                {"id": artifact["document_id"]}
                if artifact
                else cursor.execute(
                    "select id from legal.documents where fingerprint = %s",
                    (parsed.fingerprint,),
                ).fetchone()
            )
            duplicate_document = document is not None
            if document:
                document_id = document["id"]
            else:
                document = cursor.execute(
                    """
                    insert into legal.documents (
                      fingerprint, source_name, source_document_id, source_kind, document_type,
                      domain, title, authority, chamber, case_number, decision_number,
                      document_date, effective_from, effective_to, canonical_source_url,
                      canonical_content_hash, parser_version, extraction_method,
                      extraction_confidence, related_legislation, domain_metadata
                    ) values (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) returning id
                    """,
                    (
                        parsed.fingerprint,
                        parsed.source_name,
                        parsed.source_document_id,
                        parsed.source_kind,
                        parsed.document_type,
                        parsed.domain,
                        parsed.title,
                        parsed.authority,
                        parsed.chamber,
                        parsed.case_number,
                        parsed.decision_number,
                        parsed.document_date,
                        parsed.effective_from,
                        parsed.effective_to,
                        parsed.canonical_source_url,
                        parsed.canonical_content_hash,
                        parsed.parser_version,
                        parsed.extraction_method,
                        parsed.extraction_confidence,
                        list(parsed.related_legislation),
                        Jsonb(parsed.domain_metadata),
                    ),
                ).fetchone()
                document_id = document["id"]

            if not artifact:
                artifact = cursor.execute(
                    """
                    insert into legal.document_artifacts (
                      document_id, source_url, storage_path, media_type, content_hash,
                      byte_length, retrieved_at
                    ) values (%s, %s, %s, %s, %s, %s, %s)
                    returning id, document_id
                    """,
                    (
                        document_id,
                        raw.source_url,
                        storage_path,
                        raw.media_type,
                        raw_hash,
                        len(raw.content),
                        raw.retrieved_at,
                    ),
                ).fetchone()

            existing_parse = cursor.execute(
                """
                select id from legal.document_parses
                where artifact_id = %s and parser_version = %s
                """,
                (artifact["id"], parsed.parser_version),
            ).fetchone()
            if existing_parse:
                if corpus_version:
                    self._pin_parse(
                        cursor, corpus_version, document_id, existing_parse["id"]
                    )
                return IngestionOutcome(
                    document_id=str(document_id),
                    artifact_id=str(artifact["id"]),
                    parse_id=str(existing_parse["id"]),
                    duplicate_document=True,
                    duplicate_artifact=duplicate_artifact,
                    chunk_count=0,
                )

            parse_row = cursor.execute(
                """
                insert into legal.document_parses (
                  document_id, artifact_id, parser_version, canonical_content_hash,
                  extraction_method, extraction_confidence, status, metadata
                ) values (%s, %s, %s, %s, %s, %s, 'processing', %s)
                returning id
                """,
                (
                    document_id,
                    artifact["id"],
                    parsed.parser_version,
                    parsed.canonical_content_hash,
                    parsed.extraction_method,
                    parsed.extraction_confidence,
                    Jsonb(parsed.parse_metadata),
                ),
            ).fetchone()
            parse_id = parse_row["id"]

            unit_ids: dict[str, UUID] = {}
            for unit in parsed.legal_units:
                parent_id = unit_ids.get(unit.parent_key) if unit.parent_key else None
                row = cursor.execute(
                    """
                    insert into legal.legal_units (
                      parse_id, parent_unit_id, unit_index, unit_key, unit_path,
                      unit_type, label, heading, text, page_number, char_start, char_end,
                      content_hash, extraction_method, confidence, review_status, metadata
                    ) values (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s
                    ) returning id
                    """,
                    (
                        parse_id,
                        parent_id,
                        unit.unit_index,
                        unit.unit_key,
                        list(unit.unit_path),
                        unit.unit_type,
                        unit.label,
                        unit.heading,
                        unit.text,
                        unit.page_number,
                        unit.char_start,
                        unit.char_end,
                        unit.content_hash,
                        unit.extraction_method,
                        unit.confidence,
                        unit.review_status,
                        Jsonb(unit.metadata),
                    ),
                ).fetchone()
                unit_ids[unit.unit_key] = row["id"]

            for chunk in parsed.chunks:
                chunk_row = cursor.execute(
                    """
                    insert into legal.document_chunks (
                      document_id, parse_id, chunk_index, section_type, text, page_number,
                      char_start, char_end, content_hash, extraction_method, confidence, metadata
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning id
                    """,
                    (
                        document_id,
                        parse_id,
                        chunk.chunk_index,
                        chunk.section_type,
                        chunk.text,
                        chunk.page_number,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.content_hash,
                        chunk.extraction_method,
                        chunk.confidence,
                        Jsonb(chunk.metadata),
                    ),
                ).fetchone()
                relations = [
                    (chunk_row["id"], unit_ids[key], parse_id, "primary", order)
                    for order, key in enumerate(chunk.unit_keys)
                    if key in unit_ids
                ]
                if relations:
                    cursor.executemany(
                        """
                        insert into legal.chunk_legal_units (
                          chunk_id, legal_unit_id, parse_id, relation_type, unit_order
                        ) values (%s, %s, %s, %s, %s)
                        """,
                        relations,
                    )

            for event in parsed.provision_events:
                cursor.execute(
                    """
                    insert into legal.provision_events (
                      parse_id, legal_unit_id, event_index, event_type, target_type,
                      authority, source_law_number, source_law_article, case_number,
                      decision_number, event_date, official_gazette_date,
                      official_gazette_number, effective_from, target_char_start,
                      target_char_end, raw_annotation, confidence, review_status, metadata
                    ) values (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        parse_id,
                        unit_ids.get(event.legal_unit_key),
                        event.event_index,
                        event.event_type,
                        event.target_type,
                        event.authority,
                        event.source_law_number,
                        event.source_law_article,
                        event.case_number,
                        event.decision_number,
                        event.event_date,
                        event.official_gazette_date,
                        event.official_gazette_number,
                        event.effective_from,
                        event.target_char_start,
                        event.target_char_end,
                        event.raw_annotation,
                        event.confidence,
                        event.review_status,
                        Jsonb(event.metadata),
                    ),
                )

            cursor.execute(
                """
                update legal.document_parses
                set status = 'ready', completed_at = %s
                where id = %s
                """,
                (datetime.now(UTC), parse_id),
            )
            cursor.execute(
                """
                update legal.document_parses
                set status = 'superseded'
                where document_id = %s and id <> %s and status = 'ready'
                """,
                (document_id, parse_id),
            )
            cursor.execute(
                """
                update legal.documents
                set current_parse_id = %s, parser_version = %s,
                    canonical_content_hash = %s, extraction_method = %s,
                    extraction_confidence = %s, domain_metadata = %s, updated_at = %s
                where id = %s
                """,
                (
                    parse_id,
                    parsed.parser_version,
                    parsed.canonical_content_hash,
                    parsed.extraction_method,
                    parsed.extraction_confidence,
                    Jsonb(parsed.domain_metadata),
                    datetime.now(UTC),
                    document_id,
                ),
            )
            if corpus_version:
                self._pin_parse(cursor, corpus_version, document_id, parse_id)
            return IngestionOutcome(
                document_id=str(document_id),
                artifact_id=str(artifact["id"]),
                parse_id=str(parse_id),
                duplicate_document=duplicate_document,
                duplicate_artifact=duplicate_artifact,
                chunk_count=len(parsed.chunks),
            )

    @staticmethod
    def _pin_parse(
        cursor: psycopg.Cursor, corpus_version: str, document_id: UUID, parse_id: UUID
    ) -> None:
        existing = cursor.execute(
            """
            select parse_id from legal.corpus_version_documents
            where corpus_version = %s and document_id = %s
            """,
            (corpus_version, document_id),
        ).fetchone()
        if existing:
            if existing["parse_id"] != parse_id:
                raise ValueError(
                    f"Corpus {corpus_version!r} already pins a different parse for document"
                )
            return
        cursor.execute(
            """
            insert into legal.corpus_version_documents (corpus_version, document_id, parse_id)
            values (%s, %s, %s)
            """,
            (corpus_version, document_id, parse_id),
        )

    def corpus_artifacts(self, corpus_version: str) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            rows = cursor.execute(
                """
                select
                  d.source_name, d.source_document_id, d.source_kind, d.document_type,
                  d.domain, d.title, d.authority, d.chamber, d.case_number,
                  d.decision_number, d.document_date, d.effective_from, d.effective_to,
                  d.related_legislation, d.domain_metadata,
                  a.source_url, a.storage_path, a.media_type, a.content_hash,
                  a.byte_length, a.retrieved_at
                from legal.corpus_version_documents cvd
                join legal.documents d on d.id = cvd.document_id
                join legal.document_parses p on p.id = cvd.parse_id
                join legal.document_artifacts a on a.id = p.artifact_id
                where cvd.corpus_version = %s
                order by d.source_name, d.source_document_id, d.id
                """,
                (corpus_version,),
            ).fetchall()
            return [dict(row) for row in rows]

    def document_count(self) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            row = cursor.execute("select count(*) as count from legal.documents").fetchone()
            return int(row["count"])
