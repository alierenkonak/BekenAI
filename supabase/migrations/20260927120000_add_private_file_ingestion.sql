-- Stage 4: make verified user files searchable without ever touching the global corpus.
-- A file belongs to exactly one parent: a case, or a chat that has no case. Its text is
-- split into chunks that only the trusted backend role can read; vectors live in a
-- separate private Qdrant collection keyed by the same chunk ids.

alter table public.user_files
  alter column case_id drop not null;

alter table public.user_files
  add column if not exists conversation_id uuid
    references public.conversations(id) on delete set null,
  add column if not exists page_count integer check (page_count is null or page_count >= 0),
  add column if not exists unreadable_page_count integer check (
    unreadable_page_count is null or unreadable_page_count >= 0
  ),
  add column if not exists chunks_total integer check (chunks_total is null or chunks_total >= 0),
  add column if not exists chunks_done integer check (chunks_done is null or chunks_done >= 0),
  add column if not exists embedding_model text,
  add column if not exists indexed_at timestamptz,
  add column if not exists status_before_deletion text;

create index if not exists user_files_conversation_created_idx
  on public.user_files (conversation_id, created_at desc)
  where conversation_id is not null;

alter table public.user_files drop constraint if exists user_files_declared_media_type_check;
alter table public.user_files
  add constraint user_files_declared_media_type_check check (
    declared_media_type in (
      'application/pdf',
      'text/plain',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
  );

-- uploaded: verified by a pre-Stage-4 worker and not yet indexed.
-- indexing → ready is the normal Stage 4 path; failed covers verification and indexing.
alter table public.user_files drop constraint if exists user_files_status_check;
alter table public.user_files
  add constraint user_files_status_check check (
    status in (
      'pending_upload', 'verifying', 'uploaded', 'indexing', 'ready', 'failed',
      'delete_pending', 'deleted'
    )
  );

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'user_files_single_parent_check'
      and conrelid = 'public.user_files'::regclass
  ) then
    -- Deleting a chat nulls its files' parent only after they are queued for deletion.
    alter table public.user_files
      add constraint user_files_single_parent_check check (
        num_nonnulls(case_id, conversation_id) = 1
        or status in ('delete_pending', 'deleted')
      );
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'user_files_status_before_deletion_check'
      and conrelid = 'public.user_files'::regclass
  ) then
    alter table public.user_files
      add constraint user_files_status_before_deletion_check check (
        status_before_deletion is null
        or status_before_deletion in (
          'pending_upload', 'verifying', 'uploaded', 'indexing', 'ready', 'failed'
        )
      );
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'user_files_chunk_progress_check'
      and conrelid = 'public.user_files'::regclass
  ) then
    alter table public.user_files
      add constraint user_files_chunk_progress_check check (
        chunks_done is null or chunks_total is null or chunks_done <= chunks_total
      );
  end if;
end
$block$;

alter table app_private.jobs drop constraint if exists jobs_kind_check;
alter table app_private.jobs
  add constraint jobs_kind_check check (
    kind in ('chat_generation', 'file_verification', 'file_ingest', 'file_deletion')
  );

create table if not exists public.user_file_chunks (
  id uuid primary key default gen_random_uuid(),
  file_id uuid not null references public.user_files(id) on delete cascade,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  chunk_index integer not null check (chunk_index >= 0),
  text text not null check (char_length(text) between 1 and 8000),
  section_title text check (section_title is null or char_length(section_title) <= 300),
  page_start integer check (page_start is null or page_start >= 1),
  page_end integer,
  paragraph_start integer not null check (paragraph_start >= 1),
  paragraph_end integer not null,
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  search_vector tsvector generated always as (to_tsvector('turkish', text)) stored,
  created_at timestamptz not null default now(),
  unique (file_id, chunk_index),
  check ((page_start is null) = (page_end is null)),
  check (page_end is null or page_end >= page_start),
  check (paragraph_end >= paragraph_start)
);

create index if not exists user_file_chunks_workspace_idx
  on public.user_file_chunks (workspace_id);
create index if not exists user_file_chunks_search_idx
  on public.user_file_chunks using gin (search_vector);

-- Private chunk text is read only by FastAPI/worker. Browser roles get no path to it,
-- even if a later migration grants broad default privileges.
alter table public.user_file_chunks enable row level security;
revoke all on public.user_file_chunks from public, anon, authenticated;
drop policy if exists user_file_chunks_deny_frontend on public.user_file_chunks;
create policy user_file_chunks_deny_frontend on public.user_file_chunks
  for all to anon, authenticated
  using (false)
  with check (false);

do $block$
begin
  if to_regclass('storage.buckets') is not null then
    update storage.buckets
    set allowed_mime_types = array[
      'application/pdf',
      'text/plain',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]::text[]
    where id = 'case-files';
  end if;
end
$block$;
