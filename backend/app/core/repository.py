from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.core.database import AppDatabase, get_database

if TYPE_CHECKING:
    from app.files.chunking import FileChunk
    from app.files.retrieval import PrivateScope

GENERATION_STAGES = frozenset({"retrieving", "generating", "verifying"})
# global: the legal corpus; private: the user's own files; web: pages a web search found.
CITATION_SCOPES = frozenset({"global", "private", "web"})
PROMPT_VERSIONS = {"web": "web-search-v2", "analysis": "case-analysis-v1"}
# Files past verification: their object size is known and their bytes are readable.
VERIFIED_FILE_STATUSES = ("uploaded", "indexing", "ready")
# Indexing failures a later attempt can fix; format errors (scanned PDF…) cannot.
RETRYABLE_INGEST_ERRORS = frozenset(
    {
        "job_failed",
        "model_temporarily_unavailable",
        "storage_temporarily_unavailable",
        "vector_store_temporarily_unavailable",
    }
)
# A chat waits for these: answering while a document is half-indexed would silently
# ignore the part the user just uploaded. pending_upload is excluded because an
# abandoned upload intent would otherwise lock the chat until it expires.
FILES_IN_PROGRESS = ("verifying", "uploaded", "indexing")
# Rows of one chat's scope: its own uploads, and inside a case the case's files.
_SCOPE_FILES = """
  f.workspace_id = %(workspace_id)s
  and (f.conversation_id = %(conversation_id)s
       or (%(case_id)s::uuid is not null and f.case_id = %(case_id)s::uuid))
"""
_QUEUE_FILE_DELETIONS = """
with doomed as (
  update public.user_files
  set status_before_deletion = case
        when status = 'delete_pending' then status_before_deletion else status end,
      status = 'delete_pending',
      updated_at = now()
  where workspace_id = %(workspace_id)s and status <> 'deleted' and {scope}
  returning id, workspace_id
)
insert into app_private.jobs (kind, workspace_id, subject_id, idempotency_key, payload)
select 'file_deletion', workspace_id, id, 'file-delete:' || id::text, '{{}}'::jsonb from doomed
on conflict (workspace_id, idempotency_key) do update
set status='queued',attempt_count=0,available_at=now(),locked_at=null,
    locked_by=null,safe_error_code=null,completed_at=null
where app_private.jobs.status in ('failed','cancelled')
"""


class NotFoundError(RuntimeError):
    pass


class ConflictError(RuntimeError):
    pass


class CapacityExceededError(RuntimeError):
    pass


class CitationIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    next_cursor: tuple[datetime, UUID] | None


class AppRepository:
    def __init__(self, database: AppDatabase) -> None:
        self.database = database

    async def _workspace(self, conn: AsyncConnection, user_id: UUID) -> dict[str, Any]:
        row = await (
            await conn.execute(
                "select * from public.workspaces where owner_user_id = %s",
                (user_id,),
            )
        ).fetchone()
        if not row:
            raise NotFoundError("workspace_not_found")
        return row

    async def bootstrap(self, user_id: UUID, email: str | None) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            profile = await (
                await conn.execute(
                    """
                    insert into public.profiles (user_id)
                    values (%s)
                    on conflict (user_id) do update set updated_at = public.profiles.updated_at
                    returning *
                    """,
                    (user_id,),
                )
            ).fetchone()
            workspace = await (
                await conn.execute(
                    """
                    insert into public.workspaces (owner_user_id)
                    values (%s)
                    on conflict (owner_user_id) do update
                      set updated_at = public.workspaces.updated_at
                    returning *
                    """,
                    (user_id,),
                )
            ).fetchone()
        return {"profile": profile, "workspace": workspace, "email": email}

    async def get_me(self, user_id: UUID, email: str | None) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            row = await (
                await conn.execute(
                    """
                    select p.user_id, p.display_name, p.created_at, p.updated_at,
                           w.id as workspace_id
                    from public.profiles p
                    left join public.workspaces w on w.owner_user_id = p.user_id
                    where p.user_id = %s
                    """,
                    (user_id,),
                )
            ).fetchone()
        if not row:
            raise NotFoundError("profile_not_found")
        return {**row, "email": email}

    async def get_workspace(self, user_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            return await self._workspace(conn, user_id)

    async def create_case(
        self, user_id: UUID, name: str, description: str | None
    ) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            return await (
                await conn.execute(
                    """
                    insert into public.cases (workspace_id, name, description)
                    values (%s, %s, %s) returning *
                    """,
                    (workspace["id"], name, description),
                )
            ).fetchone()

    async def list_cases(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> Page:
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            params: list[Any] = [workspace["id"]]
            condition = ""
            if cursor:
                condition = "and (created_at, id) < (%s, %s)"
                params.extend(cursor)
            params.append(limit + 1)
            rows = await (
                await conn.execute(
                    f"""select * from public.cases
                    where workspace_id = %s and archived_at is null {condition}
                    order by created_at desc, id desc limit %s""",
                    params,
                )
            ).fetchall()
        return self._page(rows, limit)

    async def get_case(self, user_id: UUID, case_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            row = await (
                await conn.execute(
                    """select c.* from public.cases c
                    join public.workspaces w on w.id=c.workspace_id
                    where c.id=%s and w.owner_user_id=%s and c.archived_at is null""",
                    (case_id, user_id),
                )
            ).fetchone()
        if not row:
            raise NotFoundError("case_not_found")
        return row

    async def update_case(
        self,
        user_id: UUID,
        case_id: UUID,
        *,
        name: str | None,
        description: str | None,
        description_set: bool,
    ) -> dict[str, Any]:
        current = await self.get_case(user_id, case_id)
        async with await self.database.connect() as conn:
            row = await (
                await conn.execute(
                    """
                    update public.cases set name=%s, description=%s, updated_at=now()
                    where id=%s and workspace_id=%s returning *
                    """,
                    (
                        name if name is not None else current["name"],
                        description if description_set else current["description"],
                        case_id,
                        current["workspace_id"],
                    ),
                )
            ).fetchone()
        return row

    async def delete_case(self, user_id: UUID, case_id: UUID) -> None:
        current = await self.get_case(user_id, case_id)
        async with await self.database.connect() as conn:
            await conn.execute(
                """update public.cases set archived_at=now(),updated_at=now()
                where id=%s and workspace_id=%s""",
                (case_id, current["workspace_id"]),
            )
            # An archived case is gone for the user, so its documents and their
            # private chunks and vectors must go too.
            await conn.execute(
                _QUEUE_FILE_DELETIONS.format(scope="case_id = %(case_id)s"),
                {"workspace_id": current["workspace_id"], "case_id": case_id},
            )

    async def create_conversation(
        self,
        user_id: UUID,
        *,
        title: str,
        domain_code: str,
        case_id: UUID | None,
        doctrine_enabled: bool,
    ) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            await self._assert_case(conn, workspace["id"], case_id)
            return await (
                await conn.execute(
                    """
                    insert into public.conversations
                      (workspace_id, case_id, title, domain_code, doctrine_enabled)
                    values (%s, %s, %s, %s, %s) returning *
                    """,
                    (workspace["id"], case_id, title, domain_code, doctrine_enabled),
                )
            ).fetchone()

    async def list_conversations(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
        case_id: UUID | None,
    ) -> Page:
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            params: list[Any] = [workspace["id"]]
            conditions = ["workspace_id=%s", "archived_at is null"]
            if case_id:
                await self._assert_case(conn, workspace["id"], case_id)
                conditions.append("case_id=%s")
                params.append(case_id)
            if cursor:
                conditions.append("(created_at,id)<(%s,%s)")
                params.extend(cursor)
            params.append(limit + 1)
            rows = await (
                await conn.execute(
                    f"""select * from public.conversations
                    where {" and ".join(conditions)}
                    order by created_at desc,id desc limit %s""",
                    params,
                )
            ).fetchall()
        return self._page(rows, limit)

    async def get_conversation(self, user_id: UUID, conversation_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            row = await (
                await conn.execute(
                    """select c.* from public.conversations c
                    join public.workspaces w on w.id=c.workspace_id
                    where c.id=%s and w.owner_user_id=%s and c.archived_at is null""",
                    (conversation_id, user_id),
                )
            ).fetchone()
        if not row:
            raise NotFoundError("conversation_not_found")
        return row

    async def update_conversation(
        self,
        user_id: UUID,
        conversation_id: UUID,
        *,
        title: str | None,
        case_id: UUID | None,
        case_id_set: bool,
        doctrine_enabled: bool | None,
    ) -> dict[str, Any]:
        current = await self.get_conversation(user_id, conversation_id)
        new_case = case_id if case_id_set else current["case_id"]
        async with await self.database.connect() as conn:
            await self._assert_case(conn, current["workspace_id"], new_case)
            return await (
                await conn.execute(
                    """update public.conversations
                    set title=%s,case_id=%s,doctrine_enabled=%s,updated_at=now()
                    where id=%s and workspace_id=%s returning *""",
                    (
                        title or current["title"],
                        new_case,
                        doctrine_enabled
                        if doctrine_enabled is not None
                        else current["doctrine_enabled"],
                        conversation_id,
                        current["workspace_id"],
                    ),
                )
            ).fetchone()

    async def delete_conversation(self, user_id: UUID, conversation_id: UUID) -> None:
        current = await self.get_conversation(user_id, conversation_id)
        async with await self.database.connect() as conn:
            # Queue first: the delete below nulls these files' parent, which the
            # single-parent check only allows once they are pending deletion.
            await conn.execute(
                _QUEUE_FILE_DELETIONS.format(scope="conversation_id = %(conversation_id)s"),
                {"workspace_id": current["workspace_id"], "conversation_id": conversation_id},
            )
            await conn.execute(
                "delete from public.conversations where id=%s and workspace_id=%s",
                (conversation_id, current["workspace_id"]),
            )

    async def list_messages(
        self,
        user_id: UUID,
        conversation_id: UUID,
        *,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> Page:
        conversation = await self.get_conversation(user_id, conversation_id)
        params: list[Any] = [conversation_id, conversation["workspace_id"]]
        condition = ""
        if cursor:
            condition = "and (created_at,id)<(%s,%s)"
            params.extend(cursor)
        params.append(limit + 1)
        async with await self.database.connect() as conn:
            rows = await (
                await conn.execute(
                    f"""select * from public.messages
                    where conversation_id=%s and workspace_id=%s {condition}
                    order by created_at desc,id desc limit %s""",
                    params,
                )
            ).fetchall()
            page = self._page(rows, limit)
            await self._attach_message_details(conn, conversation["workspace_id"], page.items)
        return page

    async def _attach_message_details(
        self, conn: AsyncConnection, workspace_id: UUID, messages: list[dict[str, Any]]
    ) -> None:
        # A conversation reloaded later must render the same citations and in-flight
        # progress the live generation endpoint returns, without one request per message.
        if not messages:
            return
        message_ids = [message["id"] for message in messages]
        generations = await (
            await conn.execute(
                """select id,user_message_id,assistant_message_id,status,stage,answer_status,
                          safe_error_code,include_doctrine,search_mode,latency_ms,
                          corpus_versions,index_versions,created_at,started_at,completed_at
                   from public.chat_generations
                   where workspace_id=%s
                     and (user_message_id=any(%s) or assistant_message_id=any(%s))""",
                (workspace_id, message_ids, message_ids),
            )
        ).fetchall()
        generation_by_message: dict[UUID, dict[str, Any]] = {}
        for generation in generations:
            generation_by_message[generation["user_message_id"]] = generation
            if generation["assistant_message_id"]:
                generation_by_message[generation["assistant_message_id"]] = generation
        assistant_ids = [message["id"] for message in messages if message["role"] == "assistant"]
        citations: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        if assistant_ids:
            rows = await (
                await conn.execute(
                    """select message_id,claim_id,source_id,source_scope,source_channel,
                              source_snapshot,integrity_status,support_status,support_reason,
                              ordinal
                       from public.message_citations
                       where workspace_id=%s and message_id=any(%s)
                       order by message_id,ordinal""",
                    (workspace_id, assistant_ids),
                )
            ).fetchall()
            for row in rows:
                citations[row.pop("message_id")].append(row)
        for message in messages:
            message["generation"] = generation_by_message.get(message["id"])
            if message["role"] == "assistant":
                message["citations"] = citations.get(message["id"], [])

    async def enqueue_chat(
        self,
        user_id: UUID,
        *,
        idempotency_key: str,
        conversation_id: UUID | None,
        case_id: UUID | None,
        message: str,
        domain_code: str,
        include_doctrine: bool,
        retrieval_query: str,
        requested_model: str,
        max_active_jobs: int = 2,
        search_mode: str = "corpus",
    ) -> dict[str, Any]:
        if max_active_jobs < 1:
            raise ValueError("max_active_jobs_must_be_positive")
        job_key = f"chat:{idempotency_key}"
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            await conn.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                (f"{workspace['id']}:{job_key}",),
            )
            existing = await (
                await conn.execute(
                    """
                    select g.id as generation_id,g.conversation_id,g.user_message_id,g.status
                    from app_private.jobs j
                    join public.chat_generations g on g.id=j.subject_id
                    where j.workspace_id=%s and j.idempotency_key=%s
                    """,
                    (workspace["id"], job_key),
                )
            ).fetchone()
            if existing:
                return existing

            await self._assert_case(conn, workspace["id"], case_id)
            conversation = None
            if conversation_id:
                conversation = await (
                    await conn.execute(
                        """select * from public.conversations
                        where id=%s and workspace_id=%s and archived_at is null""",
                        (conversation_id, workspace["id"]),
                    )
                ).fetchone()
                if not conversation:
                    raise NotFoundError("conversation_not_found")
                if conversation["domain_code"] != domain_code:
                    raise ConflictError("conversation_domain_mismatch")
                if case_id is not None and conversation["case_id"] != case_id:
                    raise ConflictError("conversation_case_mismatch")

            await conn.execute(
                "select pg_advisory_xact_lock(hashtext(%s))",
                (f"chat-capacity:{workspace['id']}",),
            )
            active = await (
                await conn.execute(
                    """select count(*) as count from app_private.jobs
                    where workspace_id=%s and kind='chat_generation'
                      and status in ('queued','processing')""",
                    (workspace["id"],),
                )
            ).fetchone()
            if int(active["count"]) >= max_active_jobs:
                raise CapacityExceededError("chat_capacity_exceeded")

            busy = await (
                await conn.execute(
                    f"""select 1 from public.user_files f
                    where {_SCOPE_FILES} and f.status = any(%(statuses)s) limit 1""",
                    {
                        "workspace_id": workspace["id"],
                        "conversation_id": conversation["id"] if conversation else None,
                        "case_id": conversation["case_id"] if conversation else case_id,
                        "statuses": list(FILES_IN_PROGRESS),
                    },
                )
            ).fetchone()
            if busy:
                raise ConflictError("files_processing")

            title = " ".join(message.split())[:80]
            if search_mode == "analysis":
                # An analysis reads a case's files; a chat outside a case has none to read.
                analysed_case = conversation["case_id"] if conversation else case_id
                if analysed_case is None:
                    raise ConflictError("analysis_requires_case")
                case = await (
                    await conn.execute(
                        """select c.name,exists(
                              select 1 from public.user_files f
                              where f.workspace_id=c.workspace_id and f.case_id=c.id
                                and f.status='ready') as has_ready_files
                           from public.cases c where c.id=%s and c.workspace_id=%s""",
                        (analysed_case, workspace["id"]),
                    )
                ).fetchone()
                if not case or not case["has_ready_files"]:
                    raise ConflictError("case_has_no_ready_files")
                title = f"Dosya analizi: {' '.join(case['name'].split())}"[:160]

            if conversation is None:
                conversation = await (
                    await conn.execute(
                        """
                        insert into public.conversations
                          (workspace_id,case_id,title,domain_code,doctrine_enabled)
                        values (%s,%s,%s,%s,%s) returning *
                        """,
                        (workspace["id"], case_id, title, domain_code, include_doctrine),
                    )
                ).fetchone()

            user_message = await (
                await conn.execute(
                    """insert into public.messages
                    (workspace_id,conversation_id,role,content,status)
                    values (%s,%s,'user',%s,'completed') returning *""",
                    (workspace["id"], conversation["id"], message),
                )
            ).fetchone()
            generation = await (
                await conn.execute(
                    """insert into public.chat_generations
                    (workspace_id,conversation_id,user_message_id,requested_model,prompt_version,
                     retrieval_query,include_doctrine,search_mode)
                    values (%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
                    (
                        workspace["id"],
                        conversation["id"],
                        user_message["id"],
                        requested_model,
                        PROMPT_VERSIONS.get(search_mode, "grounded-chat-v2"),
                        retrieval_query,
                        include_doctrine,
                        search_mode,
                    ),
                )
            ).fetchone()
            await conn.execute(
                """insert into app_private.jobs
                (kind,workspace_id,subject_id,idempotency_key,payload)
                values ('chat_generation',%s,%s,%s,%s::jsonb)""",
                (workspace["id"], generation["id"], job_key, "{}"),
            )
            await conn.execute(
                "update public.conversations set updated_at=now() where id=%s",
                (conversation["id"],),
            )
        return {
            "generation_id": generation["id"],
            "conversation_id": conversation["id"],
            "user_message_id": user_message["id"],
            "status": generation["status"],
        }

    async def get_generation(self, user_id: UUID, generation_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            generation = await (
                await conn.execute(
                    """select g.*,m.content as assistant_content,
                              m.structured_content as assistant_structured_content
                    from public.chat_generations g
                    join public.workspaces w on w.id=g.workspace_id
                    left join public.messages m on m.id=g.assistant_message_id
                    where g.id=%s and w.owner_user_id=%s""",
                    (generation_id, user_id),
                )
            ).fetchone()
            if not generation:
                raise NotFoundError("generation_not_found")
            citations = []
            if generation["assistant_message_id"]:
                citations = await (
                    await conn.execute(
                        """select claim_id,source_id,source_scope,source_channel,source_snapshot,
                                  integrity_status,support_status,support_reason,ordinal
                        from public.message_citations where message_id=%s order by ordinal""",
                        (generation["assistant_message_id"],),
                    )
                ).fetchall()
        return {**generation, "citations": citations}

    async def cancel_generation(self, user_id: UUID, generation_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            generation = await (
                await conn.execute(
                    """update public.chat_generations
                    set status='cancelled',completed_at=now(),safe_error_code='cancelled_by_user'
                    where id=%s and workspace_id=%s and status in ('queued','processing')
                    returning *""",
                    (generation_id, workspace["id"]),
                )
            ).fetchone()
            if not generation:
                existing = await (
                    await conn.execute(
                        "select * from public.chat_generations where id=%s and workspace_id=%s",
                        (generation_id, workspace["id"]),
                    )
                ).fetchone()
                if not existing:
                    raise NotFoundError("generation_not_found")
                raise ConflictError("generation_not_cancellable")
            await conn.execute(
                """update app_private.jobs set status='cancelled',completed_at=now()
                where subject_id=%s and kind='chat_generation'
                  and status in ('queued','processing')""",
                (generation_id,),
            )
        return generation

    async def create_file_intent(
        self,
        user_id: UUID,
        *,
        case_id: UUID | None = None,
        conversation_id: UUID | None = None,
        original_name: str,
        safe_name: str,
        media_type: str,
        size_bytes: int,
        reservation_bytes: int,
        bucket: str,
        quota_bytes: int,
    ) -> dict[str, Any]:
        if (case_id is None) == (conversation_id is None):
            raise ValueError("file_parent_required")
        if reservation_bytes < size_bytes or reservation_bytes > quota_bytes:
            raise ValueError("invalid_file_reservation")
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            if conversation_id is not None:
                conversation = await self._owned_conversation(
                    conn, workspace["id"], conversation_id
                )
                # A chat inside a case shares its documents with the case's other chats.
                if conversation["case_id"] is not None:
                    case_id, conversation_id = conversation["case_id"], None
            await self._assert_case(conn, workspace["id"], case_id)
            await conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(user_id),))
            usage = await (
                await conn.execute(
                    # Verified files are charged their real size; anything else may
                    # still hold an object of up to the reserved size.
                    """select coalesce(sum(coalesce(verified_size_bytes,reserved_size_bytes)),0)
                       as bytes from public.user_files
                       where workspace_id=%s and status<>'deleted'""",
                    (workspace["id"],),
                )
            ).fetchone()
            if int(usage["bytes"]) + size_bytes > quota_bytes:
                raise ConflictError("user_file_quota_exceeded")
            file_id = uuid4()
            parent = f"{case_id}" if case_id else f"conversations/{conversation_id}"
            storage_path = f"{user_id}/{workspace['id']}/{parent}/{file_id}/{safe_name}"
            return await (
                await conn.execute(
                    """insert into public.user_files
                    (id,workspace_id,case_id,conversation_id,uploader_user_id,original_name,
                     storage_bucket,storage_path,declared_media_type,expected_size_bytes,
                     reserved_size_bytes)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
                    (
                        file_id,
                        workspace["id"],
                        case_id,
                        conversation_id,
                        user_id,
                        original_name,
                        bucket,
                        storage_path,
                        media_type,
                        size_bytes,
                        reservation_bytes,
                    ),
                )
            ).fetchone()

    async def complete_file(self, user_id: UUID, file_id: UUID) -> dict[str, Any]:
        job_key = f"file-verify:{file_id}"
        async with await self.database.connect() as conn:
            await conn.execute(
                "select pg_advisory_xact_lock(hashtext(%s))", (f"file:{file_id}",)
            )
            file = await self._owned_file(conn, user_id, file_id)
            if file["status"] in VERIFIED_FILE_STATUSES:
                return file
            if file["status"] not in {"pending_upload", "verifying"}:
                raise ConflictError("file_not_completable")
            if file["status"] == "pending_upload":
                file = await (
                    await conn.execute(
                        """update public.user_files set status='verifying',updated_at=now()
                        where id=%s and status='pending_upload' and upload_expires_at>now()
                        returning *""",
                        (file_id,),
                    )
                ).fetchone()
                if not file:
                    raise ConflictError("upload_intent_expired")
            await conn.execute(
                """insert into app_private.jobs
                (kind,workspace_id,subject_id,idempotency_key,payload)
                values ('file_verification',%s,%s,%s,'{}'::jsonb)
                on conflict (workspace_id,idempotency_key) do nothing""",
                (file["workspace_id"], file_id, job_key),
            )
        return file

    async def get_file(self, user_id: UUID, file_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            return await self._owned_file(conn, user_id, file_id)

    async def list_files(self, user_id: UUID, case_id: UUID) -> list[dict[str, Any]]:
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            await self._assert_case(conn, workspace["id"], case_id)
            return await (
                await conn.execute(
                    """select * from public.user_files
                    where case_id=%s and workspace_id=%s and status<>'deleted'
                    order by created_at desc,id desc""",
                    (case_id, workspace["id"]),
                )
            ).fetchall()

    async def list_conversation_files(
        self, user_id: UUID, conversation_id: UUID
    ) -> list[dict[str, Any]]:
        """Every file a chat can draw on: its own uploads and, inside a case, the case's."""
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            conversation = await self._owned_conversation(conn, workspace["id"], conversation_id)
            return await (
                await conn.execute(
                    """select * from public.user_files
                    where workspace_id=%s and status<>'deleted'
                      and (conversation_id=%s or (%s::uuid is not null and case_id=%s))
                    order by created_at desc,id desc""",
                    (
                        workspace["id"],
                        conversation_id,
                        conversation["case_id"],
                        conversation["case_id"],
                    ),
                )
            ).fetchall()

    async def request_file_deletion(self, user_id: UUID, file_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            await conn.execute(
                "select pg_advisory_xact_lock(hashtext(%s))", (f"file:{file_id}",)
            )
            file = await self._owned_file(conn, user_id, file_id)
            if file["status"] == "deleted":
                return file
            await conn.execute(
                _QUEUE_FILE_DELETIONS.format(scope="id = %(file_id)s"),
                {"workspace_id": file["workspace_id"], "file_id": file_id},
            )
            return await self._owned_file(conn, user_id, file_id)

    async def request_file_reindex(self, user_id: UUID, file_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            await conn.execute(
                "select pg_advisory_xact_lock(hashtext(%s))", (f"file:{file_id}",)
            )
            file = await self._owned_file(conn, user_id, file_id)
            if file["status"] in {"indexing", "ready"}:
                return file
            if (
                file["status"] != "failed"
                or file["verified_size_bytes"] is None
                or file["safe_error_code"] not in RETRYABLE_INGEST_ERRORS
            ):
                raise ConflictError("file_not_reindexable")
            file = await (
                await conn.execute(
                    """update public.user_files
                    set status='indexing',safe_error_code=null,chunks_done=null,
                        chunks_total=null,updated_at=now()
                    where id=%s returning *""",
                    (file_id,),
                )
            ).fetchone()
            await self._enqueue_ingest(conn, file["workspace_id"], file_id)
        return file

    async def _owned_conversation(
        self, conn: AsyncConnection, workspace_id: UUID, conversation_id: UUID
    ) -> dict[str, Any]:
        row = await (
            await conn.execute(
                "select id,case_id from public.conversations where id=%s and workspace_id=%s",
                (conversation_id, workspace_id),
            )
        ).fetchone()
        if not row:
            raise NotFoundError("conversation_not_found")
        return row

    @staticmethod
    async def _enqueue_ingest(conn: AsyncConnection, workspace_id: UUID, file_id: UUID) -> None:
        await conn.execute(
            """insert into app_private.jobs
            (kind,workspace_id,subject_id,idempotency_key,payload)
            values ('file_ingest',%s,%s,%s,'{}'::jsonb)
            on conflict (workspace_id,idempotency_key) do update
            set status='queued',attempt_count=0,available_at=now(),locked_at=null,
                locked_by=null,safe_error_code=null,completed_at=null
            where app_private.jobs.status in ('failed','cancelled','completed')""",
            (workspace_id, file_id, f"file-ingest:{file_id}"),
        )

    async def _owned_file(
        self, conn: AsyncConnection, user_id: UUID, file_id: UUID
    ) -> dict[str, Any]:
        row = await (
            await conn.execute(
                """select f.* from public.user_files f
                join public.workspaces w on w.id=f.workspace_id
                where f.id=%s and f.uploader_user_id=%s and w.owner_user_id=%s""",
                (file_id, user_id, user_id),
            )
        ).fetchone()
        if not row:
            raise NotFoundError("file_not_found")
        return row

    async def recover_stale_jobs(self, stale_minutes: int) -> int:
        async with await self.database.connect() as conn:
            rows = await (
                await conn.execute(
                    """update app_private.jobs
                    set status='queued',locked_at=null,locked_by=null,available_at=now()
                    where status='processing'
                      and locked_at < now() - (%s * interval '1 minute')
                    returning kind,subject_id""",
                    (stale_minutes,),
                )
            ).fetchall()
            generation_ids = [row["subject_id"] for row in rows if row["kind"] == "chat_generation"]
            if generation_ids:
                await conn.execute(
                    """update public.chat_generations
                    set status='queued',started_at=null,stage=null
                    where id=any(%s) and status='processing'""",
                    (generation_ids,),
                )
        return len(rows)

    async def expire_abandoned_uploads(self, grace_minutes: int = 10) -> int:
        """Queue deletion of uploads whose intent expired (e.g. the tab was closed).

        Such a record can never complete, but it stays charged until its object is gone,
        since an upload that started in time may still have written one. The ordinary
        deletion job removes it (a missing object counts as deleted) and frees the quota.
        The grace period lets an upload that was in flight at expiry finish first.
        """
        async with await self.database.connect() as conn:
            row = await (
                await conn.execute(
                    """
                    with doomed as (
                      update public.user_files
                      set status_before_deletion=status,status='delete_pending',updated_at=now()
                      where status='pending_upload'
                        and upload_expires_at < now() - (%s * interval '1 minute')
                      returning id,workspace_id
                    ), queued as (
                      insert into app_private.jobs
                        (kind,workspace_id,subject_id,idempotency_key,payload)
                      select 'file_deletion',workspace_id,id,'file-delete:' || id::text,
                             '{}'::jsonb
                      from doomed
                      on conflict (workspace_id,idempotency_key) do update
                      set status='queued',attempt_count=0,available_at=now(),locked_at=null,
                          locked_by=null,safe_error_code=null,completed_at=null
                      where app_private.jobs.status in ('failed','cancelled')
                      returning 1
                    )
                    select count(*) as count from doomed
                    """,
                    (grace_minutes,),
                )
            ).fetchone()
        return int(row["count"])

    async def claim_job(
        self, worker_id: str, kinds: Sequence[str] | None = None
    ) -> dict[str, Any] | None:
        async with await self.database.connect() as conn:
            job = await (
                await conn.execute(
                    """select * from app_private.jobs
                    where status='queued' and available_at<=now()
                      and (%s::text[] is null or kind=any(%s::text[]))
                    order by created_at,id
                    for update skip locked limit 1""",
                    (list(kinds) if kinds else None, list(kinds) if kinds else None),
                )
            ).fetchone()
            if not job:
                return None
            job = await (
                await conn.execute(
                    """update app_private.jobs
                    set status='processing',attempt_count=attempt_count+1,
                        locked_at=now(),locked_by=%s
                    where id=%s returning *""",
                    (worker_id, job["id"]),
                )
            ).fetchone()
            if job["kind"] == "chat_generation":
                await conn.execute(
                    """update public.chat_generations
                    set status='processing',started_at=coalesce(started_at,now()),
                        attempt_count=%s,stage='retrieving'
                    where id=%s and status='queued'""",
                    (job["attempt_count"], job["subject_id"]),
                )
        return job

    async def set_generation_stage(self, generation_id: UUID, stage: str) -> None:
        if stage not in GENERATION_STAGES:
            raise ValueError("invalid_generation_stage")
        async with await self.database.connect() as conn:
            await conn.execute(
                """update public.chat_generations set stage=%s
                where id=%s and status='processing'""",
                (stage, generation_id),
            )

    async def get_chat_work(self, generation_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            work = await (
                await conn.execute(
                    """select g.*,c.domain_code,c.case_id,u.content as user_message,
                              u.created_at as user_created_at
                    from public.chat_generations g
                    join public.conversations c on c.id=g.conversation_id
                    join public.messages u on u.id=g.user_message_id
                    where g.id=%s and g.status='processing'""",
                    (generation_id,),
                )
            ).fetchone()
            if not work:
                raise ConflictError("generation_not_processing")
            history = await (
                await conn.execute(
                    """select role,content,created_at,id from public.messages
                    where conversation_id=%s and id<>%s and status='completed'
                      and created_at<=%s
                    order by created_at desc,id desc limit 12""",
                    (work["conversation_id"], work["user_message_id"], work["user_created_at"]),
                )
            ).fetchall()
            checks: list[dict[str, Any]] = []
            if work["search_mode"] == "web":
                # The "Web'de ara" offer re-asks the same question. If the earlier answer
                # found provisions that changed after the case date, their old text is
                # searched too.
                earlier = await (
                    await conn.execute(
                        """select a.structured_content->'temporal_checks' as checks
                        from public.chat_generations g
                        join public.messages u on u.id=g.user_message_id
                        join public.messages a on a.id=g.assistant_message_id
                        where g.conversation_id=%s and g.id<>%s and g.status='completed'
                          and u.created_at<%s and u.content=%s
                          and a.structured_content->>'web_search_offer'='provision_changed'
                        order by u.created_at desc limit 1""",
                        (
                            work["conversation_id"],
                            work["id"],
                            work["user_created_at"],
                            work["user_message"],
                        ),
                    )
                ).fetchone()
                if earlier and isinstance(earlier["checks"], list):
                    checks = earlier["checks"]
        return {**work, "history": list(reversed(history)), "amended_checks": checks}

    async def complete_generation(self, generation_id: UUID, result: Any) -> None:
        async with await self.database.connect() as conn:
            generation = await (
                await conn.execute(
                    "select * from public.chat_generations where id=%s for update",
                    (generation_id,),
                )
            ).fetchone()
            if not generation or generation["status"] != "processing":
                raise ConflictError("generation_not_processing")
            await self._assert_citation_integrity(conn, result, generation["workspace_id"])
            assistant = await (
                await conn.execute(
                    """insert into public.messages
                    (workspace_id,conversation_id,role,content,structured_content,status)
                    values (%s,%s,'assistant',%s,%s,'completed') returning *""",
                    (
                        generation["workspace_id"],
                        generation["conversation_id"],
                        result.content,
                        Jsonb(result.structured_content),
                    ),
                )
            ).fetchone()
            for citation in result.citations:
                await conn.execute(
                    """insert into public.message_citations
                    (workspace_id,message_id,conversation_id,claim_id,source_id,source_scope,
                     source_channel,document_id,parse_id,chunk_id,file_id,file_chunk_id,
                     source_snapshot,integrity_status,support_status,support_reason,ordinal)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        generation["workspace_id"],
                        assistant["id"],
                        generation["conversation_id"],
                        citation["claim_id"],
                        citation["source_id"],
                        citation["source_scope"],
                        citation["source_channel"],
                        citation["document_id"],
                        citation["parse_id"],
                        citation["chunk_id"],
                        citation.get("file_id"),
                        citation.get("file_chunk_id"),
                        Jsonb(citation["source_snapshot"]),
                        citation["integrity_status"],
                        citation["support_status"],
                        citation["support_reason"],
                        citation["ordinal"],
                    ),
                )
            rewritten = getattr(result, "retrieval_query", None)
            if rewritten and 3 <= len(rewritten) <= 500:
                await conn.execute(
                    "update public.chat_generations set retrieval_query=%s where id=%s",
                    (rewritten, generation_id),
                )
            await conn.execute(
                """update public.chat_generations
                set assistant_message_id=%s,status='completed',answer_status=%s,
                    actual_model=%s,verifier_model=%s,fallback_used=%s,input_tokens=%s,
                    output_tokens=%s,latency_ms=%s,corpus_versions=%s,index_versions=%s,
                    safe_error_code=null,completed_at=now()
                where id=%s""",
                (
                    assistant["id"],
                    result.answer_status,
                    result.actual_model,
                    result.verifier_model,
                    result.fallback_used,
                    result.input_tokens,
                    result.output_tokens,
                    result.latency_ms,
                    Jsonb(result.corpus_versions),
                    Jsonb(result.index_versions),
                    generation_id,
                ),
            )
            await conn.execute(
                """update app_private.jobs
                set status='completed',completed_at=now(),locked_at=null,locked_by=null
                where kind='chat_generation' and subject_id=%s and status='processing'""",
                (generation_id,),
            )
            await conn.execute(
                "update public.conversations set updated_at=now() where id=%s",
                (generation["conversation_id"],),
            )

    async def fail_job(
        self,
        job: dict[str, Any],
        *,
        error_code: str,
        retryable: bool,
    ) -> None:
        retry = retryable and job["attempt_count"] < 2
        status = "queued" if retry else "failed"
        async with await self.database.connect() as conn:
            await conn.execute(
                """update app_private.jobs
                set status=%s,safe_error_code=%s,
                    available_at=case when %s then now() + interval '2 seconds'
                    else available_at end,locked_at=null,locked_by=null,
                    completed_at=case when %s then null else now() end
                where id=%s and status='processing'""",
                (status, error_code, retry, retry, job["id"]),
            )
            if job["kind"] == "chat_generation":
                await conn.execute(
                    """update public.chat_generations
                    set status=%s,safe_error_code=%s,
                        stage=case when %s then null else stage end,
                        completed_at=case when %s then null else now() end
                    where id=%s and status='processing'""",
                    (status, error_code, retry, retry, job["subject_id"]),
                )
            elif job["kind"] == "file_verification" and not retry:
                await conn.execute(
                    """update public.user_files set status='failed',safe_error_code=%s,
                        updated_at=now() where id=%s and status='verifying'""",
                    (error_code, job["subject_id"]),
                )
            elif job["kind"] == "file_ingest" and not retry:
                await conn.execute(
                    """update public.user_files set status='failed',safe_error_code=%s,
                        updated_at=now() where id=%s and status='indexing'""",
                    (error_code, job["subject_id"]),
                )
            elif job["kind"] == "file_deletion" and not retry:
                # Give the file back in the state it had, so the user can retry. A file
                # whose chat is already gone has no state to return to and stays queued.
                # Vectors are deleted first, so a searchable file may have lost them: it
                # comes back re-indexing rather than "ready" with half an index.
                restored = await (
                    await conn.execute(
                        """update public.user_files
                        set status=case when status_before_deletion in ('ready','indexing')
                                        then 'indexing'
                                        else coalesce(status_before_deletion,'uploaded') end,
                            chunks_done=case when status_before_deletion in ('ready','indexing')
                                             then null else chunks_done end,
                            chunks_total=case when status_before_deletion in ('ready','indexing')
                                              then null else chunks_total end,
                            status_before_deletion=null,safe_error_code=%s,updated_at=now()
                        where id=%s and status='delete_pending'
                          and num_nonnulls(case_id,conversation_id)=1
                        returning id,workspace_id,status""",
                        (error_code, job["subject_id"]),
                    )
                ).fetchone()
                if restored and restored["status"] == "indexing":
                    await self._enqueue_ingest(conn, restored["workspace_id"], restored["id"])

    async def cancel_job(self, job_id: UUID) -> None:
        """Close a job whose subject moved on (cancelled chat, file deleted mid-way)."""
        async with await self.database.connect() as conn:
            await conn.execute(
                """update app_private.jobs set status='cancelled',completed_at=now(),
                    locked_at=null,locked_by=null where id=%s and status='processing'""",
                (job_id,),
            )

    async def get_worker_file(self, file_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            row = await (
                await conn.execute("select * from public.user_files where id=%s", (file_id,))
            ).fetchone()
        if not row:
            raise NotFoundError("file_not_found")
        return row

    async def complete_file_verification(
        self,
        job_id: UUID,
        file_id: UUID,
        *,
        size: int,
        media_type: str,
        content_hash: str,
    ) -> None:
        async with await self.database.connect() as conn:
            updated = await (
                await conn.execute(
                    """update public.user_files
                    set status='indexing',verified_size_bytes=%s,detected_media_type=%s,
                        content_hash=%s,safe_error_code=null,chunks_done=null,
                        chunks_total=null,updated_at=now()
                    where id=%s and status='verifying' returning id,workspace_id""",
                    (size, media_type, content_hash, file_id),
                )
            ).fetchone()
            if not updated:
                raise ConflictError("file_not_verifying")
            await self._enqueue_ingest(conn, updated["workspace_id"], file_id)
            await conn.execute(
                """update app_private.jobs set status='completed',completed_at=now(),
                    locked_at=null,locked_by=null where id=%s and status='processing'""",
                (job_id,),
            )

    async def report_file_progress(
        self,
        job_id: UUID,
        file_id: UUID,
        *,
        chunks_done: int,
        chunks_total: int | None = None,
        page_count: int | None = None,
        unreadable_page_count: int | None = None,
    ) -> bool:
        """Record indexing progress and heartbeat the job; False once the file moved on."""
        async with await self.database.connect() as conn:
            updated = await (
                await conn.execute(
                    """update public.user_files
                    set chunks_done=%s,chunks_total=coalesce(%s,chunks_total),
                        page_count=coalesce(%s,page_count),
                        unreadable_page_count=coalesce(%s,unreadable_page_count),
                        updated_at=now()
                    where id=%s and status='indexing' returning id""",
                    (chunks_done, chunks_total, page_count, unreadable_page_count, file_id),
                )
            ).fetchone()
            # Long documents outlive the stale-job window; the heartbeat keeps another
            # worker from recovering (and duplicating) a job that is still running.
            await conn.execute(
                """update app_private.jobs set locked_at=now()
                where id=%s and status='processing'""",
                (job_id,),
            )
        return updated is not None

    async def complete_file_indexing(
        self,
        job_id: UUID,
        file_id: UUID,
        *,
        chunks: Sequence[FileChunk],
        chunk_ids: Sequence[UUID],
        embedding_model: str,
        page_count: int | None,
        unreadable_page_count: int,
    ) -> None:
        async with await self.database.connect() as conn:
            file = await (
                await conn.execute(
                    """select id,workspace_id,status from public.user_files
                    where id=%s for update""",
                    (file_id,),
                )
            ).fetchone()
            if not file or file["status"] != "indexing":
                raise ConflictError("file_not_indexing")
            await conn.execute("delete from public.user_file_chunks where file_id=%s", (file_id,))
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    """insert into public.user_file_chunks
                    (id,file_id,workspace_id,chunk_index,text,section_title,page_start,page_end,
                     paragraph_start,paragraph_end,content_hash)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [
                        (
                            chunk_id,
                            file_id,
                            file["workspace_id"],
                            chunk.index,
                            chunk.text,
                            chunk.section_title,
                            chunk.page_start,
                            chunk.page_end,
                            chunk.paragraph_start,
                            chunk.paragraph_end,
                            chunk.content_hash,
                        )
                        for chunk, chunk_id in zip(chunks, chunk_ids, strict=True)
                    ],
                )
            await conn.execute(
                """update public.user_files
                set status='ready',indexed_at=now(),chunks_total=%s,chunks_done=%s,
                    page_count=%s,unreadable_page_count=%s,embedding_model=%s,
                    safe_error_code=null,updated_at=now()
                where id=%s""",
                (
                    len(chunks),
                    len(chunks),
                    page_count,
                    unreadable_page_count,
                    embedding_model,
                    file_id,
                ),
            )
            await conn.execute(
                """update app_private.jobs set status='completed',completed_at=now(),
                    locked_at=null,locked_by=null where id=%s and status='processing'""",
                (job_id,),
            )

    async def resume_file_work(self) -> int:
        """Queue what an older worker or a crash left behind; safe to run on every start."""
        async with await self.database.connect() as conn:
            # Files verified before Stage 4 have never been indexed.
            resumed = await (
                await conn.execute(
                    """with pending as (
                      update public.user_files f
                      set status='indexing',chunks_done=null,chunks_total=null,updated_at=now()
                      where f.status='uploaded' and f.indexed_at is null
                        and not exists (
                          select 1 from app_private.jobs j
                          where j.kind='file_ingest' and j.subject_id=f.id
                        )
                      returning f.id,f.workspace_id
                    )
                    insert into app_private.jobs
                      (kind,workspace_id,subject_id,idempotency_key,payload)
                    select 'file_ingest',workspace_id,id,'file-ingest:' || id::text,'{}'::jsonb
                    from pending
                    on conflict (workspace_id,idempotency_key) do nothing
                    returning id"""
                )
            ).fetchall()
            # Deletions of files whose chat is gone have no owner left to retry them.
            retried = await (
                await conn.execute(
                    """update app_private.jobs j
                    set status='queued',attempt_count=0,available_at=now(),locked_at=null,
                        locked_by=null,safe_error_code=null,completed_at=null
                    from public.user_files f
                    where j.kind='file_deletion' and j.status='failed' and f.id=j.subject_id
                      and f.status='delete_pending'
                    returning j.id"""
                )
            ).fetchall()
        return len(resumed) + len(retried)

    async def complete_file_deletion(self, job_id: UUID, file_id: UUID) -> None:
        async with await self.database.connect() as conn:
            await conn.execute("delete from public.user_file_chunks where file_id=%s", (file_id,))
            # Earlier answers keep their wording, but no longer carry the file's text:
            # the quoted passage, the verifier's reason and the file name are removed.
            await conn.execute(
                """update public.message_citations
                set source_snapshot = source_snapshot
                      || jsonb_build_object('exact_passage','','title','Silinmiş dosya',
                                            'section_title',null,'redacted',true),
                    support_reason = null
                where file_id=%s""",
                (file_id,),
            )
            await conn.execute(
                """update public.user_files
                set status='deleted',status_before_deletion=null,updated_at=now()
                where id=%s and status='delete_pending'""",
                (file_id,),
            )
            await conn.execute(
                """update app_private.jobs set status='completed',completed_at=now(),
                    locked_at=null,locked_by=null where id=%s and status='processing'""",
                (job_id,),
            )

    async def get_global_source(self, document_id: UUID, chunk_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            row = await (
                await conn.execute(
                    """select d.id as document_id,d.title,d.authority,
                              d.canonical_source_url as source_url,
                              d.case_number,d.decision_number,d.document_date,
                              c.id as chunk_id,c.parse_id,c.page_number,
                              c.metadata->'breadcrumb' as breadcrumb,c.text as exact_passage,
                              c.section_type
                    from legal.documents d
                    join legal.document_chunks c on c.document_id=d.id
                    where d.id=%s and c.id=%s""",
                    (document_id, chunk_id),
                )
            ).fetchone()
        if not row:
            raise NotFoundError("source_not_found")
        return row

    async def provision_changes(self, chunk_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Dated amendment notes of the articles, paragraphs and items a law chunk covers.

        A note is tied to the smallest unit it changed; it concerns every chunk that
        overlaps that unit, so an article-level change shows on each of its chunks.
        """
        if not chunk_ids:
            return []
        async with await self.database.connect() as conn:
            return await (
                await conn.execute(
                    """select c.id as chunk_id,e.id as event_id,e.event_type,e.target_type,
                              e.event_date,e.effective_from,e.source_law_number,
                              e.raw_annotation,u.unit_path,u.unit_type
                       from legal.document_chunks c
                       join legal.provision_events e on e.parse_id=c.parse_id
                       join legal.legal_units u on u.id=e.legal_unit_id and u.parse_id=e.parse_id
                       where c.id=any(%s) and e.event_date is not null
                         and u.char_start<c.char_end and u.char_end>c.char_start
                       order by c.id,e.event_date desc,e.event_index""",
                    ([UUID(str(chunk_id)) for chunk_id in chunk_ids],),
                )
            ).fetchall()

    async def decision_texts(self, parse_ids: Sequence[str]) -> dict[str, str]:
        """The whole text of each decision parse, in reading order."""
        if not parse_ids:
            return {}
        async with await self.database.connect() as conn:
            rows = await (
                await conn.execute(
                    """select parse_id,string_agg(text,E'\\n' order by chunk_index) as body
                       from legal.document_chunks where parse_id=any(%s) group by parse_id""",
                    ([UUID(str(parse_id)) for parse_id in parse_ids],),
                )
            ).fetchall()
        return {str(row["parse_id"]): row["body"] for row in rows}

    async def article_changes(self, articles: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
        """Dated amendment notes of whole articles, by law number and article number.

        A law is found by the number that starts its title ("4857 sayılı İş Kanunu"); a note
        counts for an article when it is tied to the article or anything inside it.
        """
        if not articles:
            return []
        async with await self.database.connect() as conn:
            return await (
                await conn.execute(
                    """select r.law_number,r.article,d.title as law_title,
                              e.id as event_id,e.event_type,e.target_type,e.event_date,
                              e.effective_from,e.source_law_number,e.raw_annotation,
                              u.unit_path,u.unit_type
                       from unnest(%s::text[],%s::text[]) as r(law_number,article)
                       join legal.documents d on d.title ~ ('^' || r.law_number || ' sayılı ')
                       join legal.provision_events e on e.parse_id=d.current_parse_id
                       join legal.legal_units u on u.id=e.legal_unit_id and u.parse_id=e.parse_id
                       where e.event_date is not null
                         and ('article:' || r.article)=any(u.unit_path)
                       order by r.law_number,r.article,e.event_date desc,e.event_index""",
                    ([law for law, _ in articles], [article for _, article in articles]),
                )
            ).fetchall()

    async def _assert_citation_integrity(
        self, conn: AsyncConnection, result: Any, workspace_id: UUID
    ) -> None:
        # Conversational answers may legitimately cite nothing (a greeting, a follow-up
        # clarification); every citation that is present must still resolve exactly.
        if any(item["source_scope"] not in CITATION_SCOPES for item in result.citations):
            raise CitationIntegrityError("citation_integrity_failed")
        private = [item for item in result.citations if item["source_scope"] == "private"]
        web = [item for item in result.citations if item["source_scope"] == "web"]
        citations = [item for item in result.citations if item["source_scope"] == "global"]
        if private:
            await self._assert_private_citations(conn, private, workspace_id)
        if web:
            self._assert_web_citations(web)
        if not citations:
            return
        chunk_ids = list({UUID(str(item["chunk_id"])) for item in citations})
        rows = await (
            await conn.execute(
                """select d.id as document_id,d.title,d.authority,d.case_number,
                          d.decision_number,d.document_date,d.canonical_source_url,
                          c.id as chunk_id,c.parse_id,c.page_number,
                          c.metadata->'breadcrumb' as breadcrumb,c.text as exact_passage
                   from legal.document_chunks c
                   join legal.documents d on d.id=c.document_id
                   where c.id=any(%s)""",
                (chunk_ids,),
            )
        ).fetchall()
        by_chunk = {row["chunk_id"]: row for row in rows}
        pins = {
            (row["document_id"], row["parse_id"], row["corpus_version"])
            for row in await (
                await conn.execute(
                    """select document_id,parse_id,corpus_version
                       from legal.corpus_version_documents
                       where document_id=any(%s)""",
                    (list({UUID(str(item["document_id"])) for item in citations}),),
                )
            ).fetchall()
        }
        for citation in citations:
            snapshot = citation["source_snapshot"]
            chunk_id = UUID(str(citation["chunk_id"]))
            document_id = UUID(str(citation["document_id"]))
            parse_id = UUID(str(citation["parse_id"]))
            row = by_chunk.get(chunk_id)
            decision = snapshot.get("decision_metadata") or {}
            row_date = row["document_date"].isoformat() if row and row["document_date"] else None
            breadcrumb = row["breadcrumb"] if row and row["breadcrumb"] is not None else []
            source_url_matches = (
                snapshot.get("source_url") is None
                or row is not None
                and row["canonical_source_url"] == snapshot.get("source_url")
            )
            if (
                row is None
                or row["document_id"] != document_id
                or row["parse_id"] != parse_id
                or str(snapshot.get("document_id")) != str(document_id)
                or str(snapshot.get("parse_id")) != str(parse_id)
                or str(snapshot.get("chunk_id")) != str(chunk_id)
                or row["title"] != snapshot.get("title")
                or row["authority"] != snapshot.get("authority")
                or row["case_number"] != decision.get("case_number")
                or row["decision_number"] != decision.get("decision_number")
                or row_date != decision.get("document_date")
                or row["page_number"] != snapshot.get("page_number")
                or list(breadcrumb) != list(snapshot.get("breadcrumb") or [])
                or row["exact_passage"] != snapshot.get("exact_passage")
                or not source_url_matches
                or (document_id, parse_id, snapshot.get("corpus_version")) not in pins
            ):
                raise CitationIntegrityError("citation_integrity_failed")

    @staticmethod
    def _assert_web_citations(citations: list[dict[str, Any]]) -> None:
        """A web citation points at no stored row: its snapshot must carry the page itself."""
        for citation in citations:
            snapshot = citation["source_snapshot"]
            url = urlsplit(str(snapshot.get("source_url") or ""))
            if (
                citation["source_channel"] != "web"
                or snapshot.get("source_channel") != "web"
                or not str(citation["source_id"]).startswith("SOURCE_WEB_")
                or any(
                    citation.get(key) is not None
                    for key in ("document_id", "parse_id", "chunk_id", "file_id", "file_chunk_id")
                )
                or url.scheme not in {"http", "https"}
                or not url.netloc
                or not str(snapshot.get("exact_passage") or "").strip()
            ):
                raise CitationIntegrityError("citation_integrity_failed")

    async def _assert_private_citations(
        self, conn: AsyncConnection, citations: list[dict[str, Any]], workspace_id: UUID
    ) -> None:
        """A file citation must quote a ready file of this workspace, word for word."""
        rows = await (
            await conn.execute(
                """select c.id,c.file_id,c.text,c.page_start,c.page_end,f.original_name
                from public.user_file_chunks c
                join public.user_files f on f.id=c.file_id
                where c.id=any(%s) and c.workspace_id=%s and f.workspace_id=%s
                  and f.status='ready'""",
                (
                    list({UUID(str(item["file_chunk_id"])) for item in citations}),
                    workspace_id,
                    workspace_id,
                ),
            )
        ).fetchall()
        by_chunk = {row["id"]: row for row in rows}
        for citation in citations:
            snapshot = citation["source_snapshot"]
            row = by_chunk.get(UUID(str(citation["file_chunk_id"])))
            if (
                citation["source_channel"] != "file"
                or row is None
                or row["file_id"] != UUID(str(citation["file_id"]))
                or any(citation.get(key) is not None for key in ("document_id", "parse_id"))
                or str(snapshot.get("file_chunk_id")) != str(row["id"])
                or str(snapshot.get("file_id")) != str(row["file_id"])
                or snapshot.get("exact_passage") != row["text"]
                or snapshot.get("title") != row["original_name"]
                or snapshot.get("page_start") != row["page_start"]
                or snapshot.get("page_end") != row["page_end"]
            ):
                raise CitationIntegrityError("citation_integrity_failed")

    async def ready_file_ids(self, scope: PrivateScope) -> list[UUID]:
        async with await self.database.connect() as conn:
            rows = await (
                await conn.execute(
                    f"select f.id from public.user_files f where {_SCOPE_FILES} "
                    "and f.status='ready'",
                    {
                        "workspace_id": scope.workspace_id,
                        "conversation_id": scope.conversation_id,
                        "case_id": scope.case_id,
                    },
                )
            ).fetchall()
        return [row["id"] for row in rows]

    async def scope_file_chunks(
        self, scope: PrivateScope, *, limit: int
    ) -> list[dict[str, Any]]:
        """Every chunk of the ready files a chat can read, in reading order."""
        async with await self.database.connect() as conn:
            rows = await (
                await conn.execute(
                    f"""select c.id,c.file_id,c.chunk_index,c.text,c.section_title,
                              c.page_start,c.page_end,c.paragraph_start,c.paragraph_end,
                              f.original_name
                       from public.user_file_chunks c
                       join public.user_files f on f.id=c.file_id
                       where {_SCOPE_FILES} and f.status='ready'
                         and c.workspace_id=%(workspace_id)s
                       order by f.created_at,f.id,c.chunk_index
                       limit %(limit)s""",
                    {
                        "workspace_id": scope.workspace_id,
                        "conversation_id": scope.conversation_id,
                        "case_id": scope.case_id,
                        "limit": limit,
                    },
                )
            ).fetchall()
        return rows

    async def search_file_chunks(
        self, workspace_id: UUID, file_ids: Sequence[UUID], query: str, *, limit: int
    ) -> list[UUID]:
        """Turkish full-text ranking where any term may match.

        The snowball stemmer folds some inflections differently ("gerekçesi" and
        "gerekçeleri"), so requiring every term would drop relevant passages; the
        dense ranker and the reranker take care of precision.
        """
        if not file_ids:
            return []
        async with await self.database.connect() as conn:
            rows = await (
                await conn.execute(
                    """with q as (
                      select nullif(
                        replace(plainto_tsquery('turkish', %s)::text, ' & ', ' | '), ''
                      )::tsquery as terms
                    )
                    select c.id from public.user_file_chunks c, q
                    where q.terms is not null and c.workspace_id=%s and c.file_id=any(%s)
                      and c.search_vector @@ q.terms
                    order by ts_rank_cd(c.search_vector, q.terms) desc, c.id
                    limit %s""",
                    (query, workspace_id, list(file_ids), limit),
                )
            ).fetchall()
        return [row["id"] for row in rows]

    async def get_file_chunks(
        self, workspace_id: UUID, file_ids: Sequence[UUID], chunk_ids: Sequence[UUID]
    ) -> dict[UUID, dict[str, Any]]:
        if not chunk_ids:
            return {}
        async with await self.database.connect() as conn:
            rows = await (
                await conn.execute(
                    """select c.id,c.file_id,c.chunk_index,c.text,c.section_title,
                              c.page_start,c.page_end,c.paragraph_start,c.paragraph_end,
                              f.original_name
                    from public.user_file_chunks c
                    join public.user_files f on f.id=c.file_id
                    where c.id=any(%s) and c.workspace_id=%s and f.workspace_id=%s
                      and c.file_id=any(%s) and f.status='ready'""",
                    (list(chunk_ids), workspace_id, workspace_id, list(file_ids)),
                )
            ).fetchall()
        return {row["id"]: row for row in rows}

    async def _assert_case(
        self, conn: AsyncConnection, workspace_id: UUID, case_id: UUID | None
    ) -> None:
        if case_id is None:
            return
        exists = await (
            await conn.execute(
                """select 1 from public.cases
                where id=%s and workspace_id=%s and archived_at is null""",
                (case_id, workspace_id),
            )
        ).fetchone()
        if not exists:
            raise NotFoundError("case_not_found")

    @staticmethod
    def _page(rows: list[dict[str, Any]], limit: int) -> Page:
        items = rows[:limit]
        cursor = None
        if len(rows) > limit and items:
            cursor = (items[-1]["created_at"], items[-1]["id"])
        return Page(items=items, next_cursor=cursor)


def get_repository(database: Annotated[AppDatabase, Depends(get_database)]) -> AppRepository:
    return AppRepository(database)


Repository = Annotated[AppRepository, Depends(get_repository)]
