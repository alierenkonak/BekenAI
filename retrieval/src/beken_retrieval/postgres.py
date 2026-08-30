from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from beken_retrieval.models import ChunkRecord
from beken_retrieval.scope import RetrievalScope

_CHUNK_SELECT = """
select
  c.id as chunk_id,
  c.parse_id,
  d.id as document_id,
  d.source_document_id,
  dd.domain_code,
  cvd.corpus_version,
  dd.role as domain_role,
  d.document_type,
  d.title,
  c.text,
  c.section_type,
  c.metadata -> 'breadcrumb' as breadcrumb,
  c.page_number,
  d.authority,
  d.chamber,
  d.case_number,
  d.decision_number,
  d.document_date,
  case
    when d.source_kind = 'legislation' then coalesce(
      substring(d.source_document_id from '^law-([0-9]+)'),
      substring(d.title from '^([0-9]+)[[:space:]]+sayılı')
    )
    else null
  end as primary_legislation_number,
  case
    when d.source_kind = 'legislation' then array_remove(
      array_prepend(
        coalesce(
          substring(d.source_document_id from '^law-([0-9]+)'),
          substring(d.title from '^([0-9]+)[[:space:]]+sayılı')
        ),
        d.related_legislation
      ),
      null
    )
    else d.related_legislation
  end as legislation_numbers,
  d.canonical_source_url as source_url,
  coalesce(
    array_agg(distinct u.label order by u.label)
      filter (
        where u.unit_type in (
          'article', 'additional_article', 'temporary_article',
          'additional_temporary_article', 'repeated_article'
        ) and u.label is not null
      ),
    '{}'::text[]
  ) as article_labels
from legal.corpus_version_documents cvd
join legal.documents d on d.id = cvd.document_id
join legal.document_domains dd on dd.document_id = d.id
join legal.document_chunks c
  on c.document_id = d.id and c.parse_id = cvd.parse_id
left join legal.chunk_legal_units clu
  on clu.chunk_id = c.id and clu.parse_id = c.parse_id
left join legal.legal_units u
  on u.id = clu.legal_unit_id and u.parse_id = clu.parse_id
"""

_CHUNK_GROUP_BY = """
group by
  c.id, c.parse_id, d.id, d.source_document_id, dd.domain_code,
  cvd.corpus_version, dd.role, d.document_type, d.title, c.text,
  c.section_type, c.metadata, c.page_number, d.authority, d.chamber,
  d.case_number, d.decision_number, d.document_date,
  d.source_kind, d.source_document_id, d.related_legislation,
  d.canonical_source_url
"""


class PostgresCorpusRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def load_scope_records(
        self,
        scope: RetrievalScope,
        *,
        require_reviewed: bool = True,
    ) -> list[ChunkRecord]:
        if require_reviewed:
            scope.require_reviewed()
        query = (
            _CHUNK_SELECT
            + " where cvd.corpus_version = %s and dd.domain_code = %s "
            + _CHUNK_GROUP_BY
            + " order by d.id, c.chunk_index "
        )
        with self._connect() as connection, connection.cursor() as cursor:
            rows = cursor.execute(query, (scope.corpus_version, scope.domain)).fetchall()
        records = [self._record(row, scope.version) for row in rows]
        return [record for record in records if scope.allows(record)]

    def hydrate_chunks(
        self,
        chunk_ids: Sequence[str],
        *,
        scope: RetrievalScope,
    ) -> dict[str, ChunkRecord]:
        if not chunk_ids:
            return {}
        ids = [UUID(value) for value in chunk_ids]
        query = (
            _CHUNK_SELECT
            + " where cvd.corpus_version = %s and dd.domain_code = %s "
            + " and c.id = any(%s::uuid[]) "
            + _CHUNK_GROUP_BY
        )
        with self._connect() as connection, connection.cursor() as cursor:
            rows = cursor.execute(query, (scope.corpus_version, scope.domain, ids)).fetchall()
        records = [self._record(row, scope.version) for row in rows]
        return {record.chunk_id: record for record in records if scope.allows(record)}

    def register_scope(self, scope: RetrievalScope) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            existing = cursor.execute(
                """
                select manifest_hash, status
                from legal.retrieval_scopes
                where version = %s
                """,
                (scope.version,),
            ).fetchone()
            if (
                existing
                and existing["manifest_hash"] != scope.manifest_hash
                and existing.get("status") != "draft"
            ):
                raise ValueError(
                    f"Retrieval scope {scope.version!r} already has a different manifest"
                )
            status = "reviewed" if scope.review_status == "reviewed" else "draft"
            if existing:
                cursor.execute(
                    """
                    update legal.retrieval_scopes
                    set manifest_hash = %s,
                        manifest = %s,
                        status = %s,
                        reviewed_at = case when %s = 'reviewed' then now() else null end
                    where version = %s
                    """,
                    (
                        scope.manifest_hash,
                        Jsonb(scope.payload),
                        status,
                        status,
                        scope.version,
                    ),
                )
                return
            cursor.execute(
                """
                insert into legal.retrieval_scopes (
                  version, domain_code, corpus_version, manifest_hash, manifest, status,
                  reviewed_at
                ) values (
                  %s, %s, %s, %s, %s, %s,
                  case when %s = 'reviewed' then now() else null end
                )
                """,
                (
                    scope.version,
                    scope.domain,
                    scope.corpus_version,
                    scope.manifest_hash,
                    Jsonb(scope.payload),
                    status,
                    status,
                ),
            )

    def register_index(
        self,
        *,
        scope: RetrievalScope,
        backend: str,
        model_id: str,
        model_revision: str | None,
        index_version: str,
        manifest: dict[str, Any],
        activate: bool = True,
    ) -> str:
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        with self._connect() as connection, connection.cursor() as cursor:
            existing = cursor.execute(
                """
                select id, manifest_hash
                from legal.retrieval_indexes
                where domain_code = %s and backend = %s and index_version = %s
                """,
                (scope.domain, backend, index_version),
            ).fetchone()
            if existing and existing["manifest_hash"] != manifest_hash:
                raise ValueError("An immutable retrieval index version has different metadata")
            if existing:
                index_id = str(existing["id"])
            else:
                row = cursor.execute(
                    """
                    insert into legal.retrieval_indexes (
                      domain_code, scope_version, backend, model_id,
                      model_revision, index_version, manifest_hash, status, metadata
                    ) values (%s, %s, %s, %s, %s, %s, %s, 'ready', %s)
                    returning id
                    """,
                    (
                        scope.domain,
                        scope.version,
                        backend,
                        model_id,
                        model_revision,
                        index_version,
                        manifest_hash,
                        Jsonb(manifest),
                    ),
                ).fetchone()
                index_id = str(row["id"])
            if activate:
                cursor.execute(
                    """
                    update legal.retrieval_indexes
                    set status = 'retired'
                    where domain_code = %s and backend = %s and id <> %s
                      and status = 'ready'
                    """,
                    (scope.domain, backend, index_id),
                )
                cursor.execute(
                    """
                    update legal.retrieval_indexes
                    set status = 'ready', activated_at = now()
                    where id = %s
                    """,
                    (index_id,),
                )
            return index_id

    def activate_index(self, *, domain: str, backend: str, index_version: str) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            row = cursor.execute(
                """
                select id
                from legal.retrieval_indexes
                where domain_code = %s and backend = %s and index_version = %s
                """,
                (domain, backend, index_version),
            ).fetchone()
            if not row:
                raise ValueError("Cannot activate an unregistered retrieval index")
            cursor.execute(
                """
                update legal.retrieval_indexes
                set status = 'retired'
                where domain_code = %s and backend = %s and id <> %s
                  and status = 'ready'
                """,
                (domain, backend, row["id"]),
            )
            cursor.execute(
                """
                update legal.retrieval_indexes
                set status = 'ready', activated_at = now()
                where id = %s
                """,
                (row["id"],),
            )

    @staticmethod
    def _record(row: dict[str, Any], scope_version: str) -> ChunkRecord:
        breadcrumb = row.get("breadcrumb")
        return ChunkRecord(
            chunk_id=str(row["chunk_id"]),
            parse_id=str(row["parse_id"]),
            document_id=str(row["document_id"]),
            source_document_id=row.get("source_document_id"),
            domain_code=str(row["domain_code"]),
            corpus_version=str(row["corpus_version"]),
            retrieval_scope_version=scope_version,
            domain_role=str(row["domain_role"]),
            document_type=str(row["document_type"]),
            title=str(row["title"]),
            text=str(row["text"]),
            section_type=str(row["section_type"]),
            breadcrumb=tuple(breadcrumb) if isinstance(breadcrumb, list) else (),
            page_number=row.get("page_number"),
            authority=row.get("authority"),
            chamber=row.get("chamber"),
            case_number=row.get("case_number"),
            decision_number=row.get("decision_number"),
            document_date=row.get("document_date"),
            primary_legislation_number=row.get("primary_legislation_number"),
            legislation_numbers=tuple(row.get("legislation_numbers") or ()),
            article_labels=tuple(row.get("article_labels") or ()),
            source_url=row.get("source_url"),
        )
