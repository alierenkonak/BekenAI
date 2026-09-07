create schema if not exists app_private;

revoke all on schema app_private from public;

-- The repository's Docker CI uses plain PostgreSQL. These no-login roles and the
-- auth.uid shim make the same RLS policies testable there while remaining no-ops
-- on hosted Supabase.
do $block$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
end
$block$;

create schema if not exists auth;

do $block$
begin
  if to_regprocedure('auth.uid()') is null then
    execute $function$
      create function auth.uid()
      returns uuid
      language sql
      stable
      set search_path = ''
      as $body$
        select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
      $body$
    $function$;
  end if;
end
$block$;

create table if not exists public.profiles (
  user_id uuid primary key,
  display_name text check (display_name is null or char_length(display_name) between 1 and 100),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null unique,
  name text not null default 'Kişisel Alan' check (char_length(name) between 1 and 100),
  kind text not null default 'personal' check (kind = 'personal'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.cases (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 160),
  description text check (description is null or char_length(description) <= 2000),
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, workspace_id)
);

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  case_id uuid references public.cases(id) on delete set null,
  title text not null check (char_length(title) between 1 and 160),
  domain_code text not null references legal.domains(code) on delete restrict,
  doctrine_enabled boolean not null default false,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, workspace_id)
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  conversation_id uuid not null,
  role text not null check (role in ('user', 'assistant')),
  content text not null check (char_length(content) between 1 and 20000),
  structured_content jsonb,
  status text not null default 'completed' check (
    status in ('queued', 'processing', 'completed', 'failed', 'cancelled')
  ),
  created_at timestamptz not null default now(),
  foreign key (conversation_id, workspace_id)
    references public.conversations(id, workspace_id) on delete cascade,
  unique (id, conversation_id)
);

create table if not exists public.chat_generations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  conversation_id uuid not null,
  user_message_id uuid not null,
  assistant_message_id uuid,
  requested_model text not null,
  actual_model text,
  verifier_model text,
  prompt_version text not null,
  retrieval_query text not null check (char_length(retrieval_query) between 3 and 500),
  include_doctrine boolean not null default false,
  status text not null default 'queued' check (
    status in ('queued', 'processing', 'completed', 'failed', 'cancelled')
  ),
  answer_status text check (answer_status in ('answered', 'insufficient_evidence')),
  fallback_used boolean not null default false,
  attempt_count integer not null default 0 check (attempt_count between 0 and 2),
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  latency_ms integer check (latency_ms is null or latency_ms >= 0),
  safe_error_code text,
  corpus_versions jsonb not null default '{}'::jsonb,
  index_versions jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  foreign key (conversation_id, workspace_id)
    references public.conversations(id, workspace_id) on delete cascade,
  foreign key (user_message_id, conversation_id)
    references public.messages(id, conversation_id) on delete cascade,
  foreign key (assistant_message_id)
    references public.messages(id) on delete set null
);

create table if not exists public.message_citations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  message_id uuid not null,
  conversation_id uuid not null,
  claim_id text not null check (claim_id ~ '^[A-Za-z0-9_-]{1,80}$'),
  source_id text not null check (source_id ~ '^SOURCE_[A-Z]+_[0-9]{2}$'),
  source_scope text not null default 'global' check (source_scope in ('global', 'private')),
  source_channel text not null check (source_channel in ('primary', 'doctrine')),
  document_id uuid not null references legal.documents(id) on delete restrict,
  parse_id uuid not null references legal.document_parses(id) on delete restrict,
  chunk_id uuid not null references legal.document_chunks(id) on delete restrict,
  source_snapshot jsonb not null,
  integrity_status text not null check (integrity_status = 'valid'),
  support_status text not null check (support_status in ('supported', 'partial')),
  support_reason text check (support_reason is null or char_length(support_reason) <= 1000),
  ordinal integer not null check (ordinal >= 1),
  created_at timestamptz not null default now(),
  foreign key (message_id, conversation_id)
    references public.messages(id, conversation_id) on delete cascade,
  unique (message_id, claim_id, source_id)
);

create table if not exists public.user_files (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade,
  uploader_user_id uuid not null,
  original_name text not null check (char_length(original_name) between 1 and 255),
  storage_bucket text not null default 'case-files' check (storage_bucket = 'case-files'),
  storage_path text not null unique,
  declared_media_type text not null check (
    declared_media_type in ('application/pdf', 'text/plain')
  ),
  detected_media_type text,
  expected_size_bytes bigint not null check (
    expected_size_bytes between 1 and 52428800
  ),
  verified_size_bytes bigint check (
    verified_size_bytes is null or verified_size_bytes between 1 and 52428800
  ),
  content_hash text check (content_hash is null or content_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'pending_upload' check (
    status in (
      'pending_upload', 'verifying', 'uploaded', 'failed', 'delete_pending', 'deleted'
    )
  ),
  safe_error_code text,
  upload_expires_at timestamptz not null default (now() + interval '1 hour'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (case_id, workspace_id)
    references public.cases(id, workspace_id) on delete cascade
);

create table if not exists app_private.jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('chat_generation', 'file_verification', 'file_deletion')),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  subject_id uuid not null,
  idempotency_key text not null check (char_length(idempotency_key) between 8 and 200),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'queued' check (
    status in ('queued', 'processing', 'completed', 'failed', 'cancelled')
  ),
  attempt_count integer not null default 0 check (attempt_count between 0 and 2),
  available_at timestamptz not null default now(),
  locked_at timestamptz,
  locked_by text,
  safe_error_code text,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (workspace_id, idempotency_key)
);

create index if not exists cases_workspace_updated_idx
  on public.cases (workspace_id, updated_at desc, id desc);
create index if not exists conversations_workspace_updated_idx
  on public.conversations (workspace_id, updated_at desc, id desc);
create index if not exists conversations_case_updated_idx
  on public.conversations (case_id, updated_at desc, id desc) where case_id is not null;
create index if not exists messages_conversation_created_idx
  on public.messages (conversation_id, created_at, id);
create index if not exists chat_generations_conversation_created_idx
  on public.chat_generations (conversation_id, created_at desc, id desc);
create index if not exists message_citations_message_ordinal_idx
  on public.message_citations (message_id, ordinal);
create index if not exists user_files_workspace_status_idx
  on public.user_files (workspace_id, status, created_at desc);
create index if not exists user_files_case_created_idx
  on public.user_files (case_id, created_at desc);
create index if not exists jobs_claim_idx
  on app_private.jobs (status, available_at, created_at)
  where status = 'queued';

alter table public.profiles enable row level security;
alter table public.workspaces enable row level security;
alter table public.cases enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.chat_generations enable row level security;
alter table public.message_citations enable row level security;
alter table public.user_files enable row level security;
alter table app_private.jobs enable row level security;

drop policy if exists profiles_owner_all on public.profiles;
create policy profiles_owner_all on public.profiles
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists workspaces_owner_all on public.workspaces;
create policy workspaces_owner_all on public.workspaces
  for all to authenticated
  using ((select auth.uid()) = owner_user_id)
  with check ((select auth.uid()) = owner_user_id);

drop policy if exists cases_workspace_owner_all on public.cases;
create policy cases_workspace_owner_all on public.cases
  for all to authenticated
  using (exists (
    select 1 from public.workspaces w
    where w.id = cases.workspace_id and w.owner_user_id = (select auth.uid())
  ))
  with check (exists (
    select 1 from public.workspaces w
    where w.id = cases.workspace_id and w.owner_user_id = (select auth.uid())
  ));

drop policy if exists conversations_workspace_owner_all on public.conversations;
create policy conversations_workspace_owner_all on public.conversations
  for all to authenticated
  using (exists (
    select 1 from public.workspaces w
    where w.id = conversations.workspace_id and w.owner_user_id = (select auth.uid())
  ))
  with check (exists (
    select 1 from public.workspaces w
    where w.id = conversations.workspace_id and w.owner_user_id = (select auth.uid())
  ));

drop policy if exists messages_workspace_owner_all on public.messages;
create policy messages_workspace_owner_all on public.messages
  for all to authenticated
  using (exists (
    select 1 from public.workspaces w
    where w.id = messages.workspace_id and w.owner_user_id = (select auth.uid())
  ))
  with check (exists (
    select 1 from public.workspaces w
    where w.id = messages.workspace_id and w.owner_user_id = (select auth.uid())
  ));

drop policy if exists generations_workspace_owner_select on public.chat_generations;
create policy generations_workspace_owner_select on public.chat_generations
  for select to authenticated
  using (exists (
    select 1 from public.workspaces w
    where w.id = chat_generations.workspace_id and w.owner_user_id = (select auth.uid())
  ));

drop policy if exists citations_workspace_owner_select on public.message_citations;
create policy citations_workspace_owner_select on public.message_citations
  for select to authenticated
  using (exists (
    select 1 from public.workspaces w
    where w.id = message_citations.workspace_id and w.owner_user_id = (select auth.uid())
  ));

drop policy if exists user_files_workspace_owner_all on public.user_files;
create policy user_files_workspace_owner_all on public.user_files
  for all to authenticated
  using (
    uploader_user_id = (select auth.uid())
    and exists (
      select 1 from public.workspaces w
      where w.id = user_files.workspace_id and w.owner_user_id = (select auth.uid())
    )
  )
  with check (
    uploader_user_id = (select auth.uid())
    and exists (
      select 1 from public.workspaces w
      where w.id = user_files.workspace_id and w.owner_user_id = (select auth.uid())
    )
  );

revoke all on all tables in schema app_private from public, anon, authenticated;
revoke all on all sequences in schema app_private from public, anon, authenticated;
revoke all on public.profiles, public.workspaces, public.cases, public.conversations,
  public.messages, public.chat_generations, public.message_citations, public.user_files
  from public, anon;
grant usage on schema public to authenticated;
grant select on public.profiles, public.workspaces, public.cases, public.conversations,
  public.messages, public.chat_generations, public.message_citations, public.user_files
  to authenticated;

-- Add the auth.users foreign keys only when running inside Supabase.
do $block$
begin
  if to_regclass('auth.users') is not null then
    if not exists (
      select 1 from pg_constraint
      where conname = 'profiles_user_id_auth_users_fkey'
        and conrelid = 'public.profiles'::regclass
    ) then
      alter table public.profiles
        add constraint profiles_user_id_auth_users_fkey
        foreign key (user_id) references auth.users(id) on delete cascade;
    end if;
    if not exists (
      select 1 from pg_constraint
      where conname = 'workspaces_owner_user_auth_users_fkey'
        and conrelid = 'public.workspaces'::regclass
    ) then
      alter table public.workspaces
        add constraint workspaces_owner_user_auth_users_fkey
        foreign key (owner_user_id) references auth.users(id) on delete cascade;
    end if;
    if not exists (
      select 1 from pg_constraint
      where conname = 'user_files_uploader_auth_users_fkey'
        and conrelid = 'public.user_files'::regclass
    ) then
      alter table public.user_files
        add constraint user_files_uploader_auth_users_fkey
        foreign key (uploader_user_id) references auth.users(id) on delete cascade;
    end if;
  end if;
end
$block$;

-- Hosted/local Supabase Storage setup. Plain PostgreSQL CI skips this block.
do $block$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values (
      'case-files', 'case-files', false, 52428800,
      array['application/pdf', 'text/plain']::text[]
    )
    on conflict (id) do update
      set public = false,
          file_size_limit = excluded.file_size_limit,
          allowed_mime_types = excluded.allowed_mime_types;
  end if;
end
$block$;

do $block$
begin
  if to_regclass('storage.objects') is not null then
    execute 'drop policy if exists case_files_insert on storage.objects';
    execute $policy$
      create policy case_files_insert on storage.objects
      for insert to authenticated
      with check (
        bucket_id = 'case-files'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and exists (
          select 1 from public.user_files f
          where f.storage_bucket = bucket_id
            and f.storage_path = name
            and f.uploader_user_id = (select auth.uid())
            and f.status = 'pending_upload'
            and f.upload_expires_at > now()
        )
      )
    $policy$;
    execute 'drop policy if exists case_files_select on storage.objects';
    execute $policy$
      create policy case_files_select on storage.objects
      for select to authenticated
      using (
        bucket_id = 'case-files'
        and owner_id = (select auth.uid())::text
        and exists (
          select 1 from public.user_files f
          where f.storage_bucket = bucket_id
            and f.storage_path = name
            and f.uploader_user_id = (select auth.uid())
            and f.status not in ('deleted', 'delete_pending')
        )
      )
    $policy$;
    execute 'drop policy if exists case_files_delete on storage.objects';
    execute $policy$
      create policy case_files_delete on storage.objects
      for delete to authenticated
      using (
        bucket_id = 'case-files'
        and owner_id = (select auth.uid())::text
        and exists (
          select 1 from public.user_files f
          where f.storage_bucket = bucket_id
            and f.storage_path = name
            and f.uploader_user_id = (select auth.uid())
        )
      )
    $policy$;
  end if;
end
$block$;
