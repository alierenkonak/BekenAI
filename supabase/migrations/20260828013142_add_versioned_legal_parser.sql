-- Version parsed representations independently from immutable raw artifacts.

create table if not exists legal.document_parses (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references legal.documents(id) on delete cascade,
  artifact_id uuid not null references legal.document_artifacts(id) on delete restrict,
  parser_version text not null,
  canonical_content_hash text not null check (canonical_content_hash ~ '^[0-9a-f]{64}$'),
  extraction_method text not null,
  extraction_confidence double precision not null check (
    extraction_confidence >= 0 and extraction_confidence <= 1
  ),
  status text not null default 'ready' check (
    status in ('processing', 'ready', 'failed', 'superseded')
  ),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (artifact_id, parser_version),
  unique (id, document_id)
);

insert into legal.document_parses (
  document_id, artifact_id, parser_version, canonical_content_hash,
  extraction_method, extraction_confidence, status, metadata, completed_at
)
select
  d.id,
  artifact.id,
  d.parser_version || '-legacy',
  d.canonical_content_hash,
  d.extraction_method,
  d.extraction_confidence,
  'ready',
  jsonb_build_object('migration', 'legacy_chunk_backfill'),
  now()
from legal.documents d
join lateral (
  select da.id
  from legal.document_artifacts da
  where da.document_id = d.id
  order by da.created_at, da.id
  limit 1
) artifact on true
on conflict (artifact_id, parser_version) do nothing;

alter table legal.documents add column if not exists current_parse_id uuid;

update legal.documents d
set current_parse_id = p.id
from legal.document_parses p
where p.document_id = d.id
  and p.parser_version = d.parser_version || '-legacy'
  and d.current_parse_id is null;

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'documents_current_parse_id_fkey'
      and conrelid = 'legal.documents'::regclass
  ) then
    alter table legal.documents
      add constraint documents_current_parse_id_fkey
      foreign key (current_parse_id) references legal.document_parses(id) on delete restrict;
  end if;
end
$block$;

alter table legal.document_chunks add column if not exists parse_id uuid;

update legal.document_chunks c
set parse_id = d.current_parse_id
from legal.documents d
where d.id = c.document_id and c.parse_id is null;

alter table legal.document_chunks alter column parse_id set not null;

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'document_chunks_parse_id_fkey'
      and conrelid = 'legal.document_chunks'::regclass
  ) then
    alter table legal.document_chunks
      add constraint document_chunks_parse_id_fkey
      foreign key (parse_id) references legal.document_parses(id) on delete cascade;
  end if;
end
$block$;

alter table legal.document_chunks
  drop constraint if exists document_chunks_document_id_chunk_index_key;

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'document_chunks_parse_id_chunk_index_key'
      and conrelid = 'legal.document_chunks'::regclass
  ) then
    alter table legal.document_chunks
      add constraint document_chunks_parse_id_chunk_index_key unique (parse_id, chunk_index);
  end if;
end
$block$;

create table if not exists legal.legal_units (
  id uuid primary key default gen_random_uuid(),
  parse_id uuid not null references legal.document_parses(id) on delete cascade,
  parent_unit_id uuid references legal.legal_units(id) on delete cascade,
  unit_index integer not null check (unit_index >= 0),
  unit_key text not null,
  unit_path text[] not null default '{}',
  unit_type text not null check (unit_type in (
    'metadata', 'book', 'part', 'chapter', 'section', 'article',
    'additional_article', 'temporary_article', 'additional_temporary_article',
    'repeated_article', 'paragraph', 'item', 'subitem', 'sentence',
    'annex', 'table', 'legacy_chunk'
  )),
  label text,
  heading text,
  text text not null check (length(text) > 0),
  page_number integer check (page_number is null or page_number > 0),
  char_start integer not null check (char_start >= 0),
  char_end integer not null check (char_end > char_start),
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  extraction_method text not null,
  confidence double precision not null check (confidence >= 0 and confidence <= 1),
  review_status text not null default 'accepted' check (
    review_status in ('accepted', 'needs_review')
  ),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (parse_id, unit_index),
  unique (parse_id, unit_key),
  unique (id, parse_id)
);

insert into legal.legal_units (
  parse_id, unit_index, unit_key, unit_path, unit_type, label, text,
  page_number, char_start, char_end, content_hash, extraction_method,
  confidence, review_status, metadata
)
select
  c.parse_id,
  c.chunk_index,
  'legacy-chunk-' || c.chunk_index,
  array['legacy-chunk-' || c.chunk_index],
  'legacy_chunk',
  c.metadata ->> 'label',
  c.text,
  c.page_number,
  c.char_start,
  c.char_end,
  c.content_hash,
  c.extraction_method,
  c.confidence,
  'needs_review',
  c.metadata || '{"migration":"legacy_chunk_backfill"}'::jsonb
from legal.document_chunks c
on conflict (parse_id, unit_index) do nothing;

create table if not exists legal.provision_events (
  id uuid primary key default gen_random_uuid(),
  parse_id uuid not null references legal.document_parses(id) on delete cascade,
  legal_unit_id uuid references legal.legal_units(id) on delete cascade,
  event_index integer not null check (event_index >= 0),
  event_type text not null check (event_type in ('added', 'amended', 'repealed', 'annulled')),
  target_type text not null check (
    target_type in ('unit', 'article', 'paragraph', 'item', 'subitem', 'sentence', 'phrase')
  ),
  authority text,
  source_law_number text,
  source_law_article text,
  case_number text,
  decision_number text,
  event_date date,
  official_gazette_date date,
  official_gazette_number text,
  effective_from date,
  target_char_start integer check (target_char_start is null or target_char_start >= 0),
  target_char_end integer,
  raw_annotation text not null check (length(raw_annotation) > 0),
  confidence double precision not null check (confidence >= 0 and confidence <= 1),
  review_status text not null default 'needs_review' check (
    review_status in ('accepted', 'needs_review')
  ),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (parse_id, event_index),
  check (
    target_char_end is null
    or (target_char_start is not null and target_char_end > target_char_start)
  )
);

create table if not exists legal.provision_versions (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references legal.documents(id) on delete cascade,
  provision_key text not null,
  version_index integer not null check (version_index >= 0),
  source_legal_unit_id uuid references legal.legal_units(id) on delete set null,
  source_artifact_id uuid not null references legal.document_artifacts(id) on delete restrict,
  valid_from date,
  valid_to date,
  text text not null check (length(text) > 0),
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (document_id, provision_key, version_index),
  check (valid_to is null or valid_from is null or valid_to > valid_from)
);

create table if not exists legal.chunk_legal_units (
  chunk_id uuid not null references legal.document_chunks(id) on delete cascade,
  legal_unit_id uuid not null references legal.legal_units(id) on delete cascade,
  relation_type text not null default 'primary' check (
    relation_type in ('primary', 'context')
  ),
  unit_order integer not null check (unit_order >= 0),
  primary key (chunk_id, legal_unit_id)
);

insert into legal.chunk_legal_units (chunk_id, legal_unit_id, relation_type, unit_order)
select c.id, u.id, 'primary', 0
from legal.document_chunks c
join legal.legal_units u
  on u.parse_id = c.parse_id and u.unit_index = c.chunk_index
on conflict do nothing;

alter table legal.corpus_version_documents add column if not exists parse_id uuid;

update legal.corpus_version_documents cvd
set parse_id = d.current_parse_id
from legal.documents d
where d.id = cvd.document_id and cvd.parse_id is null;

alter table legal.corpus_version_documents alter column parse_id set not null;

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'corpus_version_documents_parse_id_fkey'
      and conrelid = 'legal.corpus_version_documents'::regclass
  ) then
    alter table legal.corpus_version_documents
      add constraint corpus_version_documents_parse_id_fkey
      foreign key (parse_id) references legal.document_parses(id) on delete restrict;
  end if;
end
$block$;

create index if not exists document_parses_document_id_idx
  on legal.document_parses (document_id, created_at desc);
create index if not exists document_parses_ready_idx
  on legal.document_parses (document_id, parser_version)
  where status = 'ready';
create index if not exists documents_current_parse_id_idx
  on legal.documents (current_parse_id);
create index if not exists document_chunks_parse_id_idx
  on legal.document_chunks (parse_id, chunk_index);
create index if not exists legal_units_parent_unit_id_idx
  on legal.legal_units (parent_unit_id);
create index if not exists legal_units_parse_type_idx
  on legal.legal_units (parse_id, unit_type, unit_index);
create index if not exists provision_events_parse_id_idx
  on legal.provision_events (parse_id, event_index);
create index if not exists provision_events_legal_unit_id_idx
  on legal.provision_events (legal_unit_id);
create index if not exists provision_versions_source_legal_unit_id_idx
  on legal.provision_versions (source_legal_unit_id);
create index if not exists provision_versions_source_artifact_id_idx
  on legal.provision_versions (source_artifact_id);
create index if not exists chunk_legal_units_legal_unit_id_idx
  on legal.chunk_legal_units (legal_unit_id);
create index if not exists corpus_version_documents_parse_id_idx
  on legal.corpus_version_documents (parse_id);

alter table legal.document_parses enable row level security;
alter table legal.legal_units enable row level security;
alter table legal.provision_events enable row level security;
alter table legal.provision_versions enable row level security;
alter table legal.chunk_legal_units enable row level security;

revoke all on legal.document_parses from public;
revoke all on legal.legal_units from public;
revoke all on legal.provision_events from public;
revoke all on legal.provision_versions from public;
revoke all on legal.chunk_legal_units from public;

do $block$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on legal.document_parses from anon';
    execute 'revoke all on legal.legal_units from anon';
    execute 'revoke all on legal.provision_events from anon';
    execute 'revoke all on legal.provision_versions from anon';
    execute 'revoke all on legal.chunk_legal_units from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on legal.document_parses from authenticated';
    execute 'revoke all on legal.legal_units from authenticated';
    execute 'revoke all on legal.provision_events from authenticated';
    execute 'revoke all on legal.provision_versions from authenticated';
    execute 'revoke all on legal.chunk_legal_units from authenticated';
  end if;
end
$block$;
