from __future__ import annotations

import os
from uuid import UUID, uuid4

import psycopg
import pytest

from app.core.config import Settings
from app.core.database import AppDatabase
from app.core.repository import AppRepository, ConflictError
from app.files.chunking import FileChunk

pytestmark = pytest.mark.skipif(
    os.getenv("BEKEN_RUN_DB_TESTS") != "1",
    reason="Set BEKEN_RUN_DB_TESTS=1 to run PostgreSQL integration tests",
)

QUOTA = 104_857_600
MAX_FILE = 52_428_800


def database_url() -> str:
    return Settings().database_url


def _repository() -> AppRepository:
    return AppRepository(AppDatabase(database_url()))


def _cleanup(*user_ids: UUID) -> None:
    with psycopg.connect(database_url()) as conn:
        for user_id in user_ids:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))


async def _intent(repository: AppRepository, user_id: UUID, **parent) -> dict:
    return await repository.create_file_intent(
        user_id,
        **parent,
        original_name="Dilekçe.pdf",
        safe_name="Dilekce.pdf",
        media_type="application/pdf",
        size_bytes=2_048,
        reservation_bytes=MAX_FILE,
        bucket="case-files",
        quota_bytes=QUOTA,
    )


def _job(kind: str, subject_id: UUID) -> dict:
    """Claim one specific job, independent of whatever else sits in the queue."""
    with psycopg.connect(database_url(), row_factory=psycopg.rows.dict_row) as conn:
        return conn.execute(
            """update app_private.jobs
            set status='processing',attempt_count=attempt_count+1,locked_at=now(),
                locked_by='integration-worker'
            where kind=%s and subject_id=%s returning *""",
            (kind, subject_id),
        ).fetchone()


def _job_status(kind: str, subject_id: UUID) -> str | None:
    with psycopg.connect(database_url()) as conn:
        row = conn.execute(
            "select status from app_private.jobs where kind=%s and subject_id=%s",
            (kind, subject_id),
        ).fetchone()
    return row[0] if row else None


async def _verified(repository: AppRepository, user_id: UUID, file: dict) -> dict:
    await repository.complete_file(user_id, file["id"])
    job = _job("file_verification", file["id"])
    await repository.complete_file_verification(
        job["id"], file["id"], size=2_048, media_type="application/pdf", content_hash="a" * 64
    )
    return await repository.get_file(user_id, file["id"])


def _chunks(texts: list[str]) -> list[FileChunk]:
    return [
        FileChunk(
            index=index,
            text=text,
            section_title="AÇIKLAMALAR",
            page_start=index + 1,
            page_end=index + 1,
            paragraph_start=index + 1,
            paragraph_end=index + 1,
            content_hash=f"{index:064x}",
        )
        for index, text in enumerate(texts)
    ]


async def _indexed(repository: AppRepository, user_id: UUID, file: dict, texts: list[str]) -> None:
    job = _job("file_ingest", file["id"])
    chunks = _chunks(texts)
    await repository.complete_file_indexing(
        job["id"],
        file["id"],
        chunks=chunks,
        chunk_ids=[uuid4() for _ in chunks],
        embedding_model="bge-m3",
        page_count=len(chunks),
        unreadable_page_count=0,
    )


@pytest.mark.asyncio
async def test_verified_file_is_indexed_into_private_chunks_and_searchable() -> None:
    user_id = uuid4()
    repository = _repository()
    try:
        await repository.bootstrap(user_id, "ingest@example.test")
        case = await repository.create_case(user_id, "İşe iade", None)
        file = await _intent(repository, user_id, case_id=case["id"])

        verified = await _verified(repository, user_id, file)
        assert verified["status"] == "indexing"
        assert _job_status("file_ingest", file["id"]) == "queued"

        job = _job("file_ingest", file["id"])
        assert await repository.report_file_progress(
            job["id"], file["id"], chunks_done=0, chunks_total=2, page_count=2,
            unreadable_page_count=0,
        )
        await repository.fail_job(job, error_code="model_temporarily_unavailable", retryable=True)
        await _indexed(
            repository,
            user_id,
            file,
            [
                "İşveren fesih gerekçesi olarak performans düşüklüğünü göstermiştir.",
                "Tanık beyanları bordro kayıtlarıyla uyumludur.",
            ],
        )

        ready = await repository.get_file(user_id, file["id"])
        assert ready["status"] == "ready"
        assert (ready["chunks_done"], ready["chunks_total"], ready["page_count"]) == (2, 2, 2)
        assert ready["indexed_at"] is not None
        assert _job_status("file_ingest", file["id"]) == "completed"
        # The Turkish stemmer folds "işverenin" onto the stored "İşveren".
        with psycopg.connect(database_url()) as conn:
            matches = conn.execute(
                """select chunk_index from public.user_file_chunks
                where file_id=%s
                  and search_vector @@ plainto_tsquery('turkish','işverenin fesih gerekçesi')""",
                (file["id"],),
            ).fetchall()
        assert matches == [(0,)]
    finally:
        _cleanup(user_id)


@pytest.mark.asyncio
async def test_deleting_a_file_while_it_indexes_stops_the_ingest_and_removes_chunks() -> None:
    user_id = uuid4()
    repository = _repository()
    try:
        await repository.bootstrap(user_id, "ingest-delete@example.test")
        case = await repository.create_case(user_id, "Silme", None)
        file = await _intent(repository, user_id, case_id=case["id"])
        await _verified(repository, user_id, file)
        job = _job("file_ingest", file["id"])

        pending = await repository.request_file_deletion(user_id, file["id"])
        assert pending["status"] == "delete_pending"
        assert pending["status_before_deletion"] == "indexing"
        assert not await repository.report_file_progress(job["id"], file["id"], chunks_done=1)
        with pytest.raises(ConflictError, match="file_not_indexing"):
            await repository.complete_file_indexing(
                job["id"], file["id"], chunks=_chunks(["metin"]), chunk_ids=[uuid4()],
                embedding_model="bge-m3", page_count=1, unreadable_page_count=0,
            )
        await repository.cancel_job(job["id"])
        assert _job_status("file_ingest", file["id"]) == "cancelled"
    finally:
        _cleanup(user_id)


@pytest.mark.asyncio
async def test_failed_deletion_restores_a_ready_file_and_success_drops_its_chunks() -> None:
    user_id = uuid4()
    repository = _repository()
    try:
        await repository.bootstrap(user_id, "ready-delete@example.test")
        case = await repository.create_case(user_id, "Hazır", None)
        file = await _intent(repository, user_id, case_id=case["id"])
        await _verified(repository, user_id, file)
        await _indexed(repository, user_id, file, ["Fesih bildirimi 15.06.2023 tarihlidir."])

        await repository.request_file_deletion(user_id, file["id"])
        job = _job("file_deletion", file["id"])
        await repository.fail_job(
            job, error_code="storage_temporarily_unavailable", retryable=False
        )
        restored = await repository.get_file(user_id, file["id"])
        assert restored["status"] == "ready" and restored["status_before_deletion"] is None

        await repository.request_file_deletion(user_id, file["id"])
        job = _job("file_deletion", file["id"])
        await repository.complete_file_deletion(job["id"], file["id"])
        deleted = await repository.get_file(user_id, file["id"])
        assert deleted["status"] == "deleted"
        with psycopg.connect(database_url()) as conn:
            remaining = conn.execute(
                "select count(*) from public.user_file_chunks where file_id=%s", (file["id"],)
            ).fetchone()[0]
        assert remaining == 0
    finally:
        _cleanup(user_id)


@pytest.mark.asyncio
async def test_chat_uploads_follow_the_chat_or_its_case() -> None:
    user_id = uuid4()
    repository = _repository()
    try:
        await repository.bootstrap(user_id, "chat-files@example.test")
        case = await repository.create_case(user_id, "Dava", None)
        loose = await repository.create_conversation(
            user_id, title="Serbest", domain_code="labour_law", case_id=None,
            doctrine_enabled=False,
        )
        in_case = await repository.create_conversation(
            user_id, title="Davada", domain_code="labour_law", case_id=case["id"],
            doctrine_enabled=False,
        )

        chat_file = await _intent(repository, user_id, conversation_id=loose["id"])
        assert chat_file["conversation_id"] == loose["id"] and chat_file["case_id"] is None
        assert f"/conversations/{loose['id']}/" in chat_file["storage_path"]
        assert chat_file["storage_path"].startswith(f"{user_id}/")

        case_file = await _intent(repository, user_id, conversation_id=in_case["id"])
        assert case_file["case_id"] == case["id"] and case_file["conversation_id"] is None

        loose_files = await repository.list_conversation_files(user_id, loose["id"])
        case_chat_files = await repository.list_conversation_files(user_id, in_case["id"])
        assert [f["id"] for f in loose_files] == [chat_file["id"]]
        assert [f["id"] for f in case_chat_files] == [case_file["id"]]

        await repository.delete_conversation(user_id, loose["id"])
        orphan = await repository.get_file(user_id, chat_file["id"])
        assert orphan["status"] == "delete_pending" and orphan["conversation_id"] is None
        assert _job_status("file_deletion", chat_file["id"]) == "queued"
        # A permanent failure cannot hand the file back to a chat that no longer exists.
        job = _job("file_deletion", chat_file["id"])
        await repository.fail_job(job, error_code="storage_delete_failed", retryable=False)
        assert (await repository.get_file(user_id, chat_file["id"]))["status"] == "delete_pending"
        assert await repository.resume_file_work() >= 1
        assert _job_status("file_deletion", chat_file["id"]) == "queued"

        await repository.delete_case(user_id, case["id"])
        assert (await repository.get_file(user_id, case_file["id"]))["status"] == "delete_pending"
        assert _job_status("file_deletion", case_file["id"]) == "queued"
    finally:
        _cleanup(user_id)


@pytest.mark.asyncio
async def test_other_users_cannot_attach_files_to_a_chat_they_do_not_own() -> None:
    owner, intruder = uuid4(), uuid4()
    repository = _repository()
    try:
        await repository.bootstrap(owner, "owner@example.test")
        await repository.bootstrap(intruder, "intruder@example.test")
        conversation = await repository.create_conversation(
            owner, title="Özel", domain_code="labour_law", case_id=None, doctrine_enabled=False
        )
        from app.core.repository import NotFoundError

        with pytest.raises(NotFoundError, match="conversation_not_found"):
            await _intent(repository, intruder, conversation_id=conversation["id"])
        with pytest.raises(NotFoundError, match="conversation_not_found"):
            await repository.list_conversation_files(intruder, conversation["id"])
    finally:
        _cleanup(owner, intruder)


@pytest.mark.asyncio
async def test_legacy_verified_files_are_queued_once_and_retryable_failures_reindex() -> None:
    user_id = uuid4()
    repository = _repository()
    try:
        await repository.bootstrap(user_id, "resume@example.test")
        case = await repository.create_case(user_id, "Eski", None)
        legacy = await _intent(repository, user_id, case_id=case["id"])
        with psycopg.connect(database_url()) as conn:
            conn.execute(
                """update public.user_files set status='uploaded',verified_size_bytes=2048
                where id=%s""",
                (legacy["id"],),
            )

        assert await repository.resume_file_work() >= 1
        assert (await repository.get_file(user_id, legacy["id"]))["status"] == "indexing"
        assert _job_status("file_ingest", legacy["id"]) == "queued"

        job = _job("file_ingest", legacy["id"])
        await repository.fail_job(job, error_code="model_temporarily_unavailable", retryable=False)
        assert (await repository.get_file(user_id, legacy["id"]))["status"] == "failed"
        requeued = await repository.request_file_reindex(user_id, legacy["id"])
        assert requeued["status"] == "indexing"
        assert _job_status("file_ingest", legacy["id"]) == "queued"

        job = _job("file_ingest", legacy["id"])
        await repository.fail_job(job, error_code="scanned_pdf_not_supported", retryable=False)
        with pytest.raises(ConflictError, match="file_not_reindexable"):
            await repository.request_file_reindex(user_id, legacy["id"])
    finally:
        _cleanup(user_id)


@pytest.mark.asyncio
async def test_quota_charges_verified_files_their_real_size() -> None:
    user_id = uuid4()
    repository = _repository()
    try:
        await repository.bootstrap(user_id, "quota4@example.test")
        case = await repository.create_case(user_id, "Kota", None)
        file = await _intent(repository, user_id, case_id=case["id"])
        await _verified(repository, user_id, file)
        # Two more 50 MB reservations fit only because the verified file counts 2 KB.
        await _intent(repository, user_id, case_id=case["id"])
        with pytest.raises(ConflictError, match="user_file_quota_exceeded"):
            await repository.create_file_intent(
                user_id, case_id=case["id"], original_name="b.pdf", safe_name="b.pdf",
                media_type="application/pdf", size_bytes=MAX_FILE, reservation_bytes=MAX_FILE,
                bucket="case-files", quota_bytes=QUOTA,
            )
    finally:
        _cleanup(user_id)


def test_private_chunks_are_invisible_to_browser_roles() -> None:
    user_id = uuid4()
    with psycopg.connect(database_url()) as conn:
        with conn.transaction(force_rollback=True):
            workspace_id = conn.execute(
                "insert into public.workspaces(owner_user_id) values (%s) returning id", (user_id,)
            ).fetchone()[0]
            case_id = conn.execute(
                "insert into public.cases(workspace_id,name) values (%s,'Dosya') returning id",
                (workspace_id,),
            ).fetchone()[0]
            file_id = conn.execute(
                """insert into public.user_files
                (workspace_id,case_id,uploader_user_id,original_name,storage_path,
                 declared_media_type,expected_size_bytes,status)
                values (%s,%s,%s,'a.txt',%s,'text/plain',1,'ready') returning id""",
                (workspace_id, case_id, user_id, f"{user_id}/{uuid4()}/a.txt"),
            ).fetchone()[0]
            conn.execute(
                """insert into public.user_file_chunks
                (file_id,workspace_id,chunk_index,text,paragraph_start,paragraph_end,content_hash)
                values (%s,%s,0,'gizli metin',1,1,%s)""",
                (file_id, workspace_id, "b" * 64),
            )
            for role in ("authenticated", "anon"):
                with conn.transaction():
                    conn.execute(f"set local role {role}")
                    conn.execute(
                        "select set_config('request.jwt.claim.sub',%s,true)", (str(user_id),)
                    )
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        with conn.transaction():
                            conn.execute("select text from public.user_file_chunks")


def test_a_live_file_must_have_exactly_one_parent() -> None:
    user_id = uuid4()
    with psycopg.connect(database_url()) as conn:
        with conn.transaction(force_rollback=True):
            workspace_id = conn.execute(
                "insert into public.workspaces(owner_user_id) values (%s) returning id", (user_id,)
            ).fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    """insert into public.user_files
                    (workspace_id,uploader_user_id,original_name,storage_path,
                     declared_media_type,expected_size_bytes,status)
                    values (%s,%s,'a.txt',%s,'text/plain',1,'ready')""",
                    (workspace_id, user_id, f"{user_id}/{uuid4()}/a.txt"),
                )
