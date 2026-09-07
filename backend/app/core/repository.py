from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.core.database import AppDatabase, get_database


class NotFoundError(RuntimeError):
    pass


class ConflictError(RuntimeError):
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
        return self._page(rows, limit)

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
    ) -> dict[str, Any]:
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
            else:
                title = " ".join(message.split())[:80]
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
                     retrieval_query,include_doctrine)
                    values (%s,%s,%s,%s,'grounded-chat-v1',%s,%s) returning *""",
                    (
                        workspace["id"],
                        conversation["id"],
                        user_message["id"],
                        requested_model,
                        retrieval_query,
                        include_doctrine,
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
        case_id: UUID,
        original_name: str,
        safe_name: str,
        media_type: str,
        size_bytes: int,
        bucket: str,
        quota_bytes: int,
    ) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            workspace = await self._workspace(conn, user_id)
            await self._assert_case(conn, workspace["id"], case_id)
            await conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(user_id),))
            usage = await (
                await conn.execute(
                    """select coalesce(sum(coalesce(verified_size_bytes,expected_size_bytes)),0)
                       as bytes from public.user_files
                       where workspace_id=%s and status not in ('failed','deleted')
                         and (status<>'pending_upload' or upload_expires_at>now())""",
                    (workspace["id"],),
                )
            ).fetchone()
            if int(usage["bytes"]) + size_bytes > quota_bytes:
                raise ConflictError("user_file_quota_exceeded")
            file_id = uuid4()
            storage_path = f"{user_id}/{workspace['id']}/{case_id}/{file_id}/{safe_name}"
            return await (
                await conn.execute(
                    """insert into public.user_files
                    (id,workspace_id,case_id,uploader_user_id,original_name,storage_bucket,
                     storage_path,declared_media_type,expected_size_bytes)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
                    (
                        file_id,
                        workspace["id"],
                        case_id,
                        user_id,
                        original_name,
                        bucket,
                        storage_path,
                        media_type,
                        size_bytes,
                    ),
                )
            ).fetchone()

    async def complete_file(self, user_id: UUID, file_id: UUID) -> dict[str, Any]:
        job_key = f"file-verify:{file_id}"
        async with await self.database.connect() as conn:
            file = await self._owned_file(conn, user_id, file_id)
            if file["status"] == "uploaded":
                return file
            if file["status"] not in {"pending_upload", "verifying"}:
                raise ConflictError("file_not_completable")
            file = await (
                await conn.execute(
                    """update public.user_files set status='verifying',updated_at=now()
                    where id=%s returning *""",
                    (file_id,),
                )
            ).fetchone()
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

    async def request_file_deletion(self, user_id: UUID, file_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            file = await self._owned_file(conn, user_id, file_id)
            if file["status"] == "deleted":
                return file
            file = await (
                await conn.execute(
                    """update public.user_files set status='delete_pending',updated_at=now()
                    where id=%s returning *""",
                    (file_id,),
                )
            ).fetchone()
            await conn.execute(
                """insert into app_private.jobs
                (kind,workspace_id,subject_id,idempotency_key,payload)
                values ('file_deletion',%s,%s,%s,'{}'::jsonb)
                on conflict (workspace_id,idempotency_key) do update
                set status='queued',attempt_count=0,available_at=now(),locked_at=null,
                    locked_by=null,safe_error_code=null,completed_at=null
                where app_private.jobs.status='failed'""",
                (file["workspace_id"], file_id, f"file-delete:{file_id}"),
            )
        return file

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
                    """update public.chat_generations set status='queued',started_at=null
                    where id=any(%s) and status='processing'""",
                    (generation_ids,),
                )
        return len(rows)

    async def claim_job(self, worker_id: str) -> dict[str, Any] | None:
        async with await self.database.connect() as conn:
            job = await (
                await conn.execute(
                    """select * from app_private.jobs
                    where status='queued' and available_at<=now()
                    order by created_at,id
                    for update skip locked limit 1"""
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
                        attempt_count=%s
                    where id=%s and status='queued'""",
                    (job["attempt_count"], job["subject_id"]),
                )
        return job

    async def get_chat_work(self, generation_id: UUID) -> dict[str, Any]:
        async with await self.database.connect() as conn:
            work = await (
                await conn.execute(
                    """select g.*,c.domain_code,u.content as user_message,
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
        return {**work, "history": list(reversed(history))}

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
            await self._assert_citation_integrity(conn, result)
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
                     source_channel,document_id,parse_id,chunk_id,source_snapshot,
                     integrity_status,support_status,support_reason,ordinal)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
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
                        Jsonb(citation["source_snapshot"]),
                        citation["integrity_status"],
                        citation["support_status"],
                        citation["support_reason"],
                        citation["ordinal"],
                    ),
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
                        completed_at=case when %s then null else now() end
                    where id=%s and status='processing'""",
                    (status, error_code, retry, job["subject_id"]),
                )
            elif job["kind"] == "file_verification" and not retry:
                await conn.execute(
                    """update public.user_files set status='failed',safe_error_code=%s,
                        updated_at=now() where id=%s and status='verifying'""",
                    (error_code, job["subject_id"]),
                )
            elif job["kind"] == "file_deletion" and not retry:
                await conn.execute(
                    """update public.user_files set status='uploaded',safe_error_code=%s,
                        updated_at=now() where id=%s and status='delete_pending'""",
                    (error_code, job["subject_id"]),
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
                    set status='uploaded',verified_size_bytes=%s,detected_media_type=%s,
                        content_hash=%s,safe_error_code=null,updated_at=now()
                    where id=%s and status='verifying' returning id""",
                    (size, media_type, content_hash, file_id),
                )
            ).fetchone()
            if not updated:
                raise ConflictError("file_not_verifying")
            await conn.execute(
                """update app_private.jobs set status='completed',completed_at=now(),
                    locked_at=null,locked_by=null where id=%s and status='processing'""",
                (job_id,),
            )

    async def complete_file_deletion(self, job_id: UUID, file_id: UUID) -> None:
        async with await self.database.connect() as conn:
            await conn.execute(
                """update public.user_files set status='deleted',updated_at=now()
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

    async def _assert_citation_integrity(self, conn: AsyncConnection, result: Any) -> None:
        citations = result.citations
        if result.answer_status == "answered" and not citations:
            raise CitationIntegrityError("citation_integrity_failed")
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
