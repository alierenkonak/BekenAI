from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest

from app.core.config import Settings
from app.core.database import AppDatabase
from app.core.repository import (
    AppRepository,
    CapacityExceededError,
    CitationIntegrityError,
    ConflictError,
    NotFoundError,
)

pytestmark = pytest.mark.skipif(
    os.getenv("BEKEN_RUN_DB_TESTS") != "1",
    reason="Set BEKEN_RUN_DB_TESTS=1 to run PostgreSQL integration tests",
)


def database_url() -> str:
    return Settings().database_url


def test_stage3_rls_isolates_two_users_and_denies_anon() -> None:
    first, second = uuid4(), uuid4()
    with psycopg.connect(database_url()) as conn:
        with conn.transaction(force_rollback=True):
            first_workspace = conn.execute(
                "insert into public.workspaces(owner_user_id) values (%s) returning id", (first,)
            ).fetchone()[0]
            second_workspace = conn.execute(
                "insert into public.workspaces(owner_user_id) values (%s) returning id", (second,)
            ).fetchone()[0]
            conn.execute(
                "insert into public.cases(workspace_id,name) values (%s,'Birinci dosya')",
                (first_workspace,),
            )
            conn.execute(
                "insert into public.cases(workspace_id,name) values (%s,'İkinci dosya')",
                (second_workspace,),
            )

            conn.execute("set local role authenticated")
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(first),))
            names = [row[0] for row in conn.execute("select name from public.cases")]
            assert names == ["Birinci dosya"]

    with psycopg.connect(database_url()) as conn:
        with conn.transaction(force_rollback=True):
            conn.execute("set local role anon")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("select * from public.workspaces")


def test_private_job_queue_is_not_exposed_to_frontend_roles() -> None:
    with psycopg.connect(database_url()) as conn:
        privileges = conn.execute(
            """select
                has_table_privilege('anon','app_private.jobs','select'),
                has_table_privilege('authenticated','app_private.jobs','select'),
                has_table_privilege('authenticated','public.chat_generations','insert'),
                has_table_privilege('authenticated','public.message_citations','insert'),
                has_table_privilege('authenticated','public.user_files','select'),
                has_table_privilege('authenticated','public.user_files','insert'),
                has_table_privilege('authenticated','public.user_files','update'),
                has_table_privilege('authenticated','public.user_files','delete'),
                has_table_privilege('authenticated','public.user_files','truncate'),
                has_table_privilege('authenticated','public.user_files','references'),
                has_table_privilege('authenticated','public.user_files','trigger'),
                has_table_privilege('authenticated','public.cases','delete'),
                has_table_privilege('authenticated','public.cases','truncate'),
                has_table_privilege('authenticated','public.workspaces','delete'),
                has_table_privilege('authenticated','public.workspaces','truncate')"""
        ).fetchone()
        policies = conn.execute(
            """select cmd, roles from pg_policies
            where schemaname='public' and tablename='user_files'
            order by policyname"""
        ).fetchall()
    assert privileges[:5] == (False, False, False, False, True)
    assert privileges[5:] == (False,) * 10
    assert policies == [("SELECT", ["authenticated"])]


def test_authenticated_user_files_are_read_only() -> None:
    user_id, file_id = uuid4(), uuid4()
    with psycopg.connect(database_url()) as conn:
        with conn.transaction(force_rollback=True):
            workspace_id = conn.execute(
                "insert into public.workspaces(owner_user_id) values (%s) returning id",
                (user_id,),
            ).fetchone()[0]
            case_id = conn.execute(
                "insert into public.cases(workspace_id,name) values (%s,'Dosya') returning id",
                (workspace_id,),
            ).fetchone()[0]
            conn.execute(
                """insert into public.user_files
                (id,workspace_id,case_id,uploader_user_id,original_name,storage_path,
                 declared_media_type,expected_size_bytes)
                values (%s,%s,%s,%s,'belge.txt',%s,'text/plain',1)""",
                (
                    file_id,
                    workspace_id,
                    case_id,
                    user_id,
                    f"{user_id}/{workspace_id}/{case_id}/{file_id}/belge.txt",
                ),
            )

            conn.execute("set local role authenticated")
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(user_id),))
            assert conn.execute(
                "select id from public.user_files where id=%s", (file_id,)
            ).fetchone() == (file_id,)

            blocked_statements = (
                ("update public.user_files set status='failed' where id=%s", (file_id,)),
                ("delete from public.user_files where id=%s", (file_id,)),
                ("truncate table public.user_files", None),
                ("delete from public.cases where id=%s", (case_id,)),
                ("truncate table public.cases", None),
                ("delete from public.workspaces where id=%s", (workspace_id,)),
                ("truncate table public.workspaces", None),
            )
            for statement, params in blocked_statements:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with conn.transaction():
                        conn.execute(statement, params)


def test_all_user_tables_have_rls_enabled() -> None:
    expected = {
        "profiles",
        "workspaces",
        "cases",
        "conversations",
        "messages",
        "chat_generations",
        "message_citations",
        "user_files",
    }
    with psycopg.connect(database_url()) as conn:
        enabled = {
            row[0]
            for row in conn.execute(
                """select tablename from pg_tables where schemaname='public'
                and rowsecurity and tablename=any(%s)""",
                (list(expected),),
            )
        }
    assert enabled == expected


@pytest.mark.asyncio
async def test_chat_idempotency_and_stale_job_recovery() -> None:
    user_id = uuid4()
    repository = AppRepository(AppDatabase(database_url()))
    try:
        await repository.bootstrap(user_id, "integration@example.test")
        first = await repository.enqueue_chat(
            user_id,
            idempotency_key="integration-idempotency",
            conversation_id=None,
            case_id=None,
            message="Fesih bildirimi nasıl yapılır?",
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="fesih bildirimi nasıl yapılır",
            requested_model="fixture-model",
        )
        second = await repository.enqueue_chat(
            user_id,
            idempotency_key="integration-idempotency",
            conversation_id=None,
            case_id=None,
            message="Bu tekrar kaydedilmemeli.",
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="bu tekrar kaydedilmemeli",
            requested_model="fixture-model",
        )
        assert first["generation_id"] == second["generation_id"]
        with psycopg.connect(database_url()) as conn:
            job = conn.execute(
                """update app_private.jobs set status='processing',locked_by='fixture',
                    locked_at=now()-interval '20 minutes'
                    where subject_id=%s returning id""",
                (first["generation_id"],),
            ).fetchone()
            assert job
            conn.execute(
                "update public.chat_generations set status='processing' where id=%s",
                (first["generation_id"],),
            )
        assert await repository.recover_stale_jobs(10) == 1
        generation = await repository.get_generation(user_id, first["generation_id"])
        assert generation["status"] == "queued"
    finally:
        with psycopg.connect(database_url()) as conn:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))


@pytest.mark.asyncio
async def test_chat_capacity_is_bounded_without_breaking_idempotent_retries() -> None:
    user_id = uuid4()
    repository = AppRepository(AppDatabase(database_url()))
    try:
        await repository.bootstrap(user_id, "capacity@example.test")
        first = await repository.enqueue_chat(
            user_id,
            idempotency_key="capacity-first",
            conversation_id=None,
            case_id=None,
            message="Birinci soru",
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="birinci soru",
            requested_model="fixture-model",
            max_active_jobs=2,
        )
        await repository.enqueue_chat(
            user_id,
            idempotency_key="capacity-second",
            conversation_id=None,
            case_id=None,
            message="İkinci soru",
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="ikinci soru",
            requested_model="fixture-model",
            max_active_jobs=2,
        )

        replay = await repository.enqueue_chat(
            user_id,
            idempotency_key="capacity-first",
            conversation_id=None,
            case_id=None,
            message="Tekrar gönderim",
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="tekrar gönderim",
            requested_model="fixture-model",
            max_active_jobs=2,
        )
        assert replay["generation_id"] == first["generation_id"]

        with pytest.raises(NotFoundError, match="case_not_found"):
            await repository.enqueue_chat(
                user_id,
                idempotency_key="capacity-invalid-case",
                conversation_id=None,
                case_id=uuid4(),
                message="Geçersiz dosya",
                domain_code="labour_law",
                include_doctrine=False,
                retrieval_query="geçersiz dosya",
                requested_model="fixture-model",
                max_active_jobs=2,
            )

        with pytest.raises(CapacityExceededError, match="chat_capacity_exceeded"):
            await repository.enqueue_chat(
                user_id,
                idempotency_key="capacity-third",
                conversation_id=None,
                case_id=None,
                message="Üçüncü soru",
                domain_code="labour_law",
                include_doctrine=False,
                retrieval_query="üçüncü soru",
                requested_model="fixture-model",
                max_active_jobs=2,
            )

        await repository.cancel_generation(user_id, first["generation_id"])
        third = await repository.enqueue_chat(
            user_id,
            idempotency_key="capacity-third",
            conversation_id=None,
            case_id=None,
            message="Üçüncü soru",
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="üçüncü soru",
            requested_model="fixture-model",
            max_active_jobs=2,
        )
        assert third["status"] == "queued"
    finally:
        with psycopg.connect(database_url()) as conn:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))


@pytest.mark.asyncio
async def test_user_file_quota_is_enforced_atomically() -> None:
    user_id = uuid4()
    repository = AppRepository(AppDatabase(database_url()))
    try:
        await repository.bootstrap(user_id, "files@example.test")
        case = await repository.create_case(user_id, "Dosya", None)
        for index in range(2):
            await repository.create_file_intent(
                user_id,
                case_id=case["id"],
                original_name=f"dosya-{index}.pdf",
                safe_name=f"dosya-{index}.pdf",
                media_type="application/pdf",
                size_bytes=52_428_800,
                reservation_bytes=52_428_800,
                bucket="case-files",
                quota_bytes=104_857_600,
            )
        with pytest.raises(ConflictError, match="user_file_quota_exceeded"):
            await repository.create_file_intent(
                user_id,
                case_id=case["id"],
                original_name="fazla.txt",
                safe_name="fazla.txt",
                media_type="text/plain",
                size_bytes=1,
                reservation_bytes=52_428_800,
                bucket="case-files",
                quota_bytes=104_857_600,
            )
    finally:
        with psycopg.connect(database_url()) as conn:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))


@pytest.mark.asyncio
async def test_failed_and_expired_uploads_stay_reserved_until_deleted() -> None:
    user_id = uuid4()
    repository = AppRepository(AppDatabase(database_url()))
    try:
        await repository.bootstrap(user_id, "reserved-files@example.test")
        case = await repository.create_case(user_id, "Dosya", None)
        failed = await repository.create_file_intent(
            user_id,
            case_id=case["id"],
            original_name="failed.pdf",
            safe_name="failed.pdf",
            media_type="application/pdf",
            size_bytes=1,
            reservation_bytes=52_428_800,
            bucket="case-files",
            quota_bytes=104_857_600,
        )
        with psycopg.connect(database_url()) as conn:
            conn.execute(
                "update public.user_files set status='failed' where id=%s",
                (failed["id"],),
            )
        expired = await repository.create_file_intent(
            user_id,
            case_id=case["id"],
            original_name="expired.pdf",
            safe_name="expired.pdf",
            media_type="application/pdf",
            size_bytes=1,
            reservation_bytes=52_428_800,
            bucket="case-files",
            quota_bytes=104_857_600,
        )
        with psycopg.connect(database_url()) as conn:
            conn.execute(
                "update public.user_files set upload_expires_at=now()-interval '1 second' "
                "where id=%s",
                (expired["id"],),
            )

        with pytest.raises(ConflictError, match="upload_intent_expired"):
            await repository.complete_file(user_id, expired["id"])
        with pytest.raises(ConflictError, match="user_file_quota_exceeded"):
            await repository.create_file_intent(
                user_id,
                case_id=case["id"],
                original_name="third.pdf",
                safe_name="third.pdf",
                media_type="application/pdf",
                size_bytes=1,
                reservation_bytes=52_428_800,
                bucket="case-files",
                quota_bytes=104_857_600,
            )

        # An expired pending upload must remain reserved until its deletion job
        # completes, then the user can create another upload intent.
        deleting = await repository.request_file_deletion(user_id, expired["id"])
        assert deleting["status"] == "delete_pending"
        await repository.complete_file_deletion(uuid4(), expired["id"])
        replacement = await repository.create_file_intent(
            user_id,
            case_id=case["id"],
            original_name="replacement.pdf",
            safe_name="replacement.pdf",
            media_type="application/pdf",
            size_bytes=1,
            reservation_bytes=52_428_800,
            bucket="case-files",
            quota_bytes=104_857_600,
        )
        assert replacement["status"] == "pending_upload"
    finally:
        with psycopg.connect(database_url()) as conn:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))


@pytest.mark.asyncio
async def test_generation_rejects_unresolvable_citation_before_persisting_answer() -> None:
    user_id = uuid4()
    repository = AppRepository(AppDatabase(database_url()))
    try:
        await repository.bootstrap(user_id, "citations@example.test")
        queued = await repository.enqueue_chat(
            user_id,
            idempotency_key="citation-integrity-fixture",
            conversation_id=None,
            case_id=None,
            message="Fesih bildirimi nasıl yapılır?",
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="fesih bildirimi nasıl yapılır",
            requested_model="fixture-model",
        )
        job = await repository.claim_job("integration-worker")
        assert job and job["subject_id"] == queued["generation_id"]
        missing_document, missing_parse, missing_chunk = uuid4(), uuid4(), uuid4()
        result = SimpleNamespace(
            answer_status="answered",
            content="Kaynaklandırılmamış cevap",
            structured_content={},
            citations=[
                {
                    "claim_id": "P1",
                    "source_id": "SOURCE_PRIMARY_01",
                    "source_scope": "global",
                    "source_channel": "primary",
                    "document_id": str(missing_document),
                    "parse_id": str(missing_parse),
                    "chunk_id": str(missing_chunk),
                    "source_snapshot": {
                        "document_id": str(missing_document),
                        "parse_id": str(missing_parse),
                        "chunk_id": str(missing_chunk),
                        "corpus_version": "missing-corpus",
                    },
                }
            ],
        )
        with pytest.raises(CitationIntegrityError, match="citation_integrity_failed"):
            await repository.complete_generation(queued["generation_id"], result)
        generation = await repository.get_generation(user_id, queued["generation_id"])
        assert generation["assistant_message_id"] is None
    finally:
        with psycopg.connect(database_url()) as conn:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))


@pytest.mark.asyncio
async def test_failed_file_deletion_can_be_requeued() -> None:
    user_id = uuid4()
    repository = AppRepository(AppDatabase(database_url()))
    try:
        await repository.bootstrap(user_id, "deletion@example.test")
        case = await repository.create_case(user_id, "Silme", None)
        file = await repository.create_file_intent(
            user_id,
            case_id=case["id"],
            original_name="belge.pdf",
            safe_name="belge.pdf",
            media_type="application/pdf",
            size_bytes=10,
            reservation_bytes=52_428_800,
            bucket="case-files",
            quota_bytes=104_857_600,
        )
        with psycopg.connect(database_url()) as conn:
            conn.execute(
                "update public.user_files set status='uploaded' where id=%s",
                (file["id"],),
            )
        await repository.request_file_deletion(user_id, file["id"])
        job = await repository.claim_job("integration-worker")
        assert job and job["kind"] == "file_deletion"
        await repository.fail_job(
            job,
            error_code="storage_temporarily_unavailable",
            retryable=False,
        )
        failed = await repository.get_file(user_id, file["id"])
        assert failed["status"] == "uploaded"
        await repository.request_file_deletion(user_id, file["id"])
        with psycopg.connect(database_url()) as conn:
            status_row = conn.execute(
                "select status,attempt_count from app_private.jobs where id=%s",
                (job["id"],),
            ).fetchone()
        assert status_row == ("queued", 0)
    finally:
        with psycopg.connect(database_url()) as conn:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))


@pytest.mark.asyncio
async def test_generation_stage_lifecycle_and_message_details() -> None:
    user_id = uuid4()
    repository = AppRepository(AppDatabase(database_url()))
    try:
        await repository.bootstrap(user_id, "stages@example.test")
        queued = await repository.enqueue_chat(
            user_id,
            idempotency_key="stage-lifecycle-fixture",
            conversation_id=None,
            case_id=None,
            message="İhbar süresi kaç haftadır?",
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="ihbar süresi kaç haftadır",
            requested_model="fixture-model",
        )
        job = await repository.claim_job("integration-worker")
        assert job and job["subject_id"] == queued["generation_id"]
        generation = await repository.get_generation(user_id, queued["generation_id"])
        assert generation["status"] == "processing"
        assert generation["stage"] == "retrieving"

        await repository.set_generation_stage(queued["generation_id"], "verifying")
        with pytest.raises(ValueError, match="invalid_generation_stage"):
            await repository.set_generation_stage(queued["generation_id"], "thinking")

        page = await repository.list_messages(
            user_id, queued["conversation_id"], limit=50, cursor=None
        )
        [user_message] = page.items
        assert user_message["generation"]["id"] == queued["generation_id"]
        assert user_message["generation"]["stage"] == "verifying"
        assert "citations" not in user_message

        await repository.fail_job(
            job, error_code="provider_temporarily_unavailable", retryable=True
        )
        generation = await repository.get_generation(user_id, queued["generation_id"])
        assert generation["status"] == "queued"
        assert generation["stage"] is None
    finally:
        with psycopg.connect(database_url()) as conn:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))


@pytest.mark.asyncio
async def test_provision_changes_follow_the_units_each_law_chunk_covers(tmp_path) -> None:
    from beken_ingestion.database import CorpusRepository
    from beken_ingestion.models import RawDocument
    from beken_ingestion.pipeline import IngestionPipeline
    from beken_ingestion.storage import FilesystemRawStorage

    pipeline = IngestionPipeline(CorpusRepository(database_url()), FilesystemRawStorage(tmp_path))
    imported = pipeline.ingest(
        RawDocument(
            source_name="manual",
            source_document_id="integration-provision-history",
            source_url="file:///integration-provision-history.txt",
            media_type="text/plain",
            content=(
                "MADDE 1 - (1) Birinci fıkra işverenin yükümlülüğünü düzenleyen bir hükümdür.\n"
                "(2) (Ek fıkra: 1/7/2006-5538/18 md.) Sonradan eklenen fıkra yeni bir şart "
                "getirir ve işçinin başvuru hakkını düzenler.\n"
                "MADDE 2 - (Değişik: 6/5/2016-6715/1 md.) Değişen madde bugünkü metniyle "
                "yürürlüktedir ve ayrıntılı bir usul öngörür.\n"
                "MADDE 3 - Hiç değişmemiş madde aynen yürürlüktedir ve bir süre öngörür.\n"
            ).encode(),
            metadata={
                "source_kind": "legislation",
                "document_type": "law",
                "domain": "labour_law",
                "title": "Provision History Kanunu",
            },
        )
    )
    try:
        with psycopg.connect(database_url()) as connection:
            chunks = connection.execute(
                """select c.id,c.text from legal.document_chunks c
                   join legal.documents d on d.current_parse_id=c.parse_id
                   where d.id=%s order by c.chunk_index""",
                (imported.document_id,),
            ).fetchall()
        rows = await AppRepository(AppDatabase(database_url())).provision_changes(
            [str(chunk_id) for chunk_id, _ in chunks]
        )
        notes: dict[str, list[tuple]] = {}
        for row in rows:
            notes.setdefault(str(row["chunk_id"]), []).append(
                (row["event_type"], row["event_date"].isoformat(), row["source_law_number"])
            )
        by_article = {
            text.split(" -", 1)[0]: notes.get(str(chunk_id), [])
            for chunk_id, text in chunks
            if text.startswith("MADDE")
        }
        assert by_article == {
            "MADDE 1": [("added", "2006-07-01", "5538")],
            "MADDE 2": [("amended", "2016-05-06", "6715")],
            "MADDE 3": [],
        }
    finally:
        with psycopg.connect(database_url()) as connection:
            connection.execute("delete from legal.documents where id=%s", (imported.document_id,))


@pytest.mark.asyncio
async def test_a_web_turn_finds_the_changed_provisions_of_the_same_earlier_question() -> None:
    user_id = uuid4()
    repository = AppRepository(AppDatabase(database_url()))
    question = "Arabuluculuk toplantısına katılmama kuralı davamızı etkiler mi?"
    check = {"level": "changed_after", "title": "7036 sayılı İş Mahkemeleri Kanunu"}

    def answered(structured: dict) -> SimpleNamespace:
        return SimpleNamespace(
            answer_status="answered",
            content="Cevap",
            structured_content=structured,
            citations=[],
            actual_model="fixture-model",
            verifier_model=None,
            fallback_used=False,
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            corpus_versions={},
            index_versions={},
        )

    async def ask(key: str, conversation_id, search_mode: str) -> dict:
        queued = await repository.enqueue_chat(
            user_id,
            idempotency_key=key,
            conversation_id=conversation_id,
            case_id=None,
            message=question,
            domain_code="labour_law",
            include_doctrine=False,
            retrieval_query="arabuluculuk toplantısına katılmama",
            requested_model="fixture-model",
            search_mode=search_mode,
        )
        job = await repository.claim_job("integration-worker")
        assert job and job["subject_id"] == queued["generation_id"]
        return queued

    try:
        await repository.bootstrap(user_id, "amended@example.test")
        first = await ask("amended-corpus", None, "corpus")
        assert (await repository.get_chat_work(first["generation_id"]))["amended_checks"] == []
        await repository.complete_generation(
            first["generation_id"],
            answered({"web_search_offer": "provision_changed", "temporal_checks": [check]}),
        )

        # The offer re-asks the same question with web search on.
        second = await ask("amended-web", first["conversation_id"], "web")
        work = await repository.get_chat_work(second["generation_id"])
        assert work["amended_checks"] == [check]
    finally:
        with psycopg.connect(database_url()) as conn:
            conn.execute("delete from public.workspaces where owner_user_id=%s", (user_id,))
            conn.execute("delete from public.profiles where user_id=%s", (user_id,))
