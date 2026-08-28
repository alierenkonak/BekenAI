create schema if not exists legal;

revoke all on schema legal from public;

do $block$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on schema legal from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on schema legal from authenticated';
  end if;
end
$block$;

create table if not exists legal.corpus_versions (
  version text primary key,
  manifest_hash text not null check (manifest_hash ~ '^[0-9a-f]{64}$'),
  manifest jsonb not null,
  status text not null default 'draft' check (status in ('draft', 'ready', 'retired')),
  created_at timestamptz not null default now(),
  published_at timestamptz
);

create table if not exists legal.documents (
  id uuid primary key default gen_random_uuid(),
  fingerprint text not null unique,
  source_name text not null,
  source_document_id text,
  source_kind text not null check (source_kind in ('legislation', 'court_decision')),
  document_type text not null,
  domain text not null default 'labour_law',
  title text not null,
  authority text,
  chamber text,
  case_number text,
  decision_number text,
  document_date date,
  effective_from date,
  effective_to date,
  canonical_source_url text,
  canonical_content_hash text not null check (canonical_content_hash ~ '^[0-9a-f]{64}$'),
  parser_version text not null,
  extraction_method text not null,
  extraction_confidence double precision not null check (
    extraction_confidence >= 0 and extraction_confidence <= 1
  ),
  related_legislation text[] not null default '{}',
  domain_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists legal.document_artifacts (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references legal.documents(id) on delete cascade,
  source_url text,
  storage_path text not null,
  media_type text not null,
  content_hash text not null unique check (content_hash ~ '^[0-9a-f]{64}$'),
  byte_length bigint not null check (byte_length >= 0),
  retrieved_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table if not exists legal.document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references legal.documents(id) on delete cascade,
  chunk_index integer not null check (chunk_index >= 0),
  section_type text not null,
  text text not null check (length(text) > 0),
  page_number integer check (page_number is null or page_number > 0),
  char_start integer not null check (char_start >= 0),
  char_end integer not null check (char_end > char_start),
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  extraction_method text not null,
  confidence double precision not null check (confidence >= 0 and confidence <= 1),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (document_id, chunk_index)
);

create table if not exists legal.ingestion_runs (
  id uuid primary key default gen_random_uuid(),
  adapter_name text not null,
  corpus_version text references legal.corpus_versions(version),
  status text not null check (status in ('running', 'completed', 'failed', 'blocked')),
  checkpoint jsonb not null default '{}'::jsonb,
  discovered_count integer not null default 0 check (discovered_count >= 0),
  imported_count integer not null default 0 check (imported_count >= 0),
  duplicate_count integer not null default 0 check (duplicate_count >= 0),
  failed_count integer not null default 0 check (failed_count >= 0),
  error_code text,
  error_detail text,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists legal.ingestion_errors (
  id bigint generated always as identity primary key,
  run_id uuid not null references legal.ingestion_runs(id) on delete cascade,
  source_url text,
  source_document_id text,
  error_code text not null,
  error_detail text not null,
  retryable boolean not null,
  attempt integer not null check (attempt > 0),
  created_at timestamptz not null default now()
);

create table if not exists legal.corpus_version_documents (
  corpus_version text not null references legal.corpus_versions(version) on delete cascade,
  document_id uuid not null references legal.documents(id) on delete cascade,
  added_at timestamptz not null default now(),
  primary key (corpus_version, document_id)
);

create index if not exists documents_source_lookup_idx
  on legal.documents (source_name, source_document_id);
create index if not exists documents_decision_lookup_idx
  on legal.documents (authority, chamber, decision_number, document_date)
  where source_kind = 'court_decision';
create index if not exists documents_domain_idx on legal.documents (domain, document_type);
create index if not exists document_chunks_document_idx
  on legal.document_chunks (document_id, chunk_index);
create index if not exists document_chunks_content_hash_idx
  on legal.document_chunks (content_hash);
create index if not exists ingestion_runs_status_idx
  on legal.ingestion_runs (status, started_at desc);

alter table legal.corpus_versions enable row level security;
alter table legal.documents enable row level security;
alter table legal.document_artifacts enable row level security;
alter table legal.document_chunks enable row level security;
alter table legal.ingestion_runs enable row level security;
alter table legal.ingestion_errors enable row level security;
alter table legal.corpus_version_documents enable row level security;

revoke all on all tables in schema legal from public;
revoke all on all sequences in schema legal from public;

do $block$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema legal from anon';
    execute 'revoke all on all sequences in schema legal from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on all tables in schema legal from authenticated';
    execute 'revoke all on all sequences in schema legal from authenticated';
  end if;
end
$block$;
