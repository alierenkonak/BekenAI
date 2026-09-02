-- Make the legal corpus domain-independent without rewriting immutable V1-V4 data.

create table if not exists legal.domains (
  code text primary key check (code ~ '^[a-z][a-z0-9_]{1,63}$'),
  display_name text not null,
  status text not null default 'experimental' check (
    status in ('experimental', 'supported', 'retired')
  ),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists legal.source_kinds (
  code text primary key check (code ~ '^[a-z][a-z0-9_]{1,63}$'),
  display_name text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists legal.document_types (
  code text primary key check (code ~ '^[a-z][a-z0-9_]{1,63}$'),
  source_kind_code text not null references legal.source_kinds(code) on delete restrict,
  display_name text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (code, source_kind_code)
);

create table if not exists legal.legal_unit_types (
  code text primary key check (code ~ '^[a-z][a-z0-9_]{1,63}$'),
  display_name text not null,
  is_structural boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

insert into legal.domains (code, display_name, status)
values ('labour_law', 'İş Hukuku', 'experimental')
on conflict (code) do update
set display_name = excluded.display_name;

insert into legal.source_kinds (code, display_name)
values
  ('legislation', 'Mevzuat'),
  ('court_decision', 'Yargı Kararı'),
  ('administrative_decision', 'İdari Karar'),
  ('administrative_guidance', 'İdari Rehberlik'),
  ('doctrine', 'Öğreti')
on conflict (code) do update
set display_name = excluded.display_name;

insert into legal.document_types (code, source_kind_code, display_name)
values
  ('law', 'legislation', 'Kanun'),
  ('regulation', 'legislation', 'Yönetmelik'),
  ('court_decision', 'court_decision', 'İçtihat Kararı'),
  ('communique', 'legislation', 'Tebliğ'),
  ('circular', 'administrative_guidance', 'Genelge'),
  ('private_ruling', 'administrative_decision', 'Özelge'),
  ('constitutional_court_decision', 'court_decision', 'AYM Kararı'),
  ('council_of_state_decision', 'court_decision', 'Danıştay Kararı'),
  ('regional_appellate_decision', 'court_decision', 'Bölge Adliye Mahkemesi Kararı'),
  ('tax_court_decision', 'court_decision', 'Vergi Mahkemesi Kararı'),
  ('academic_work', 'doctrine', 'Akademik Eser')
on conflict (code) do update
set source_kind_code = excluded.source_kind_code,
    display_name = excluded.display_name;

insert into legal.legal_unit_types (code, display_name, is_structural)
values
  ('metadata', 'Metadata', false),
  ('book', 'Kitap', true),
  ('part', 'Kısım', true),
  ('chapter', 'Bölüm', true),
  ('section', 'Ayırım', true),
  ('article', 'Madde', true),
  ('additional_article', 'Ek Madde', true),
  ('temporary_article', 'Geçici Madde', true),
  ('additional_temporary_article', 'Ek Geçici Madde', true),
  ('repeated_article', 'Mükerrer Madde', true),
  ('paragraph', 'Fıkra', true),
  ('item', 'Bent', true),
  ('subitem', 'Alt Bent', true),
  ('sentence', 'Cümle', true),
  ('annex', 'Ek', true),
  ('table', 'Cetvel/Tablo', true),
  ('legacy_chunk', 'Eski Passage', false)
on conflict (code) do update
set display_name = excluded.display_name,
    is_structural = excluded.is_structural;

-- Preserve any domain/type codes already present before foreign keys are attached.
insert into legal.domains (code, display_name, status)
select distinct d.domain, initcap(replace(d.domain, '_', ' ')), 'experimental'
from legal.documents d
where d.domain is not null and d.domain <> ''
on conflict (code) do nothing;

insert into legal.source_kinds (code, display_name)
select distinct d.source_kind, initcap(replace(d.source_kind, '_', ' '))
from legal.documents d
where d.source_kind is not null and d.source_kind <> ''
on conflict (code) do nothing;

insert into legal.document_types (code, source_kind_code, display_name)
select distinct d.document_type, d.source_kind, initcap(replace(d.document_type, '_', ' '))
from legal.documents d
where d.document_type is not null and d.document_type <> ''
on conflict (code) do nothing;

insert into legal.legal_unit_types (code, display_name)
select distinct u.unit_type, initcap(replace(u.unit_type, '_', ' '))
from legal.legal_units u
where u.unit_type is not null and u.unit_type <> ''
on conflict (code) do nothing;

alter table legal.documents alter column domain drop default;
alter table legal.documents drop constraint if exists documents_source_kind_check;
alter table legal.legal_units drop constraint if exists legal_units_unit_type_check;

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'documents_source_kind_registry_fkey'
      and conrelid = 'legal.documents'::regclass
  ) then
    alter table legal.documents
      add constraint documents_source_kind_registry_fkey
      foreign key (source_kind) references legal.source_kinds(code) on delete restrict;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'documents_document_type_source_kind_fkey'
      and conrelid = 'legal.documents'::regclass
  ) then
    alter table legal.documents
      add constraint documents_document_type_source_kind_fkey
      foreign key (document_type, source_kind)
      references legal.document_types(code, source_kind_code) on delete restrict;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'legal_units_unit_type_registry_fkey'
      and conrelid = 'legal.legal_units'::regclass
  ) then
    alter table legal.legal_units
      add constraint legal_units_unit_type_registry_fkey
      foreign key (unit_type) references legal.legal_unit_types(code) on delete restrict;
  end if;
end
$block$;

create table if not exists legal.document_domains (
  document_id uuid not null references legal.documents(id) on delete cascade,
  domain_code text not null references legal.domains(code) on delete restrict,
  role text not null check (role in ('core', 'supplemental', 'future_domain')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (document_id, domain_code)
);

create table if not exists legal.corpus_version_domains (
  corpus_version text not null references legal.corpus_versions(version) on delete cascade,
  domain_code text not null references legal.domains(code) on delete restrict,
  status text not null default 'draft' check (status in ('draft', 'ready', 'retired')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (corpus_version, domain_code)
);

create table if not exists legal.retrieval_scopes (
  version text primary key,
  domain_code text not null references legal.domains(code) on delete restrict,
  corpus_version text not null references legal.corpus_versions(version) on delete restrict,
  manifest_hash text not null check (manifest_hash ~ '^[0-9a-f]{64}$'),
  manifest jsonb not null,
  status text not null default 'draft' check (
    status in ('draft', 'reviewed', 'indexed', 'retired')
  ),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  unique (domain_code, version)
);

create table if not exists legal.retrieval_indexes (
  id uuid primary key default gen_random_uuid(),
  domain_code text not null references legal.domains(code) on delete restrict,
  scope_version text not null references legal.retrieval_scopes(version) on delete restrict,
  backend text not null,
  model_id text not null,
  model_revision text,
  index_version text not null,
  manifest_hash text not null check (manifest_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'building' check (
    status in ('building', 'ready', 'failed', 'retired')
  ),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  activated_at timestamptz,
  unique (domain_code, backend, index_version)
);

insert into legal.document_domains (document_id, domain_code, role, metadata)
select
  d.id,
  d.domain,
  case d.domain_metadata ->> 'corpus_role'
    when 'supplemental' then 'supplemental'
    when 'future_domain' then 'future_domain'
    else 'core'
  end,
  d.domain_metadata - 'corpus_role'
from legal.documents d
on conflict (document_id, domain_code) do update
set role = excluded.role,
    metadata = excluded.metadata,
    updated_at = now();

insert into legal.corpus_version_domains (corpus_version, domain_code, status)
select
  cvd.corpus_version,
  dd.domain_code,
  case cv.status
    when 'ready' then 'ready'
    when 'retired' then 'retired'
    else 'draft'
  end
from legal.corpus_version_documents cvd
join legal.corpus_versions cv on cv.version = cvd.corpus_version
join legal.document_domains dd on dd.document_id = cvd.document_id
group by cvd.corpus_version, dd.domain_code, cv.status
on conflict (corpus_version, domain_code) do update
set status = excluded.status;

create index if not exists document_domains_domain_role_document_idx
  on legal.document_domains (domain_code, role, document_id);
create index if not exists corpus_version_domains_domain_status_idx
  on legal.corpus_version_domains (domain_code, status, corpus_version);
create index if not exists document_types_source_kind_idx
  on legal.document_types (source_kind_code, code);
create index if not exists retrieval_scopes_domain_status_idx
  on legal.retrieval_scopes (domain_code, status, version);
create index if not exists retrieval_scopes_corpus_version_idx
  on legal.retrieval_scopes (corpus_version);
create index if not exists retrieval_indexes_scope_version_idx
  on legal.retrieval_indexes (scope_version);
create index if not exists retrieval_indexes_domain_status_idx
  on legal.retrieval_indexes (domain_code, status, backend);

alter table legal.domains enable row level security;
alter table legal.source_kinds enable row level security;
alter table legal.document_types enable row level security;
alter table legal.legal_unit_types enable row level security;
alter table legal.document_domains enable row level security;
alter table legal.corpus_version_domains enable row level security;
alter table legal.retrieval_scopes enable row level security;
alter table legal.retrieval_indexes enable row level security;

revoke all on legal.domains from public;
revoke all on legal.source_kinds from public;
revoke all on legal.document_types from public;
revoke all on legal.legal_unit_types from public;
revoke all on legal.document_domains from public;
revoke all on legal.corpus_version_domains from public;
revoke all on legal.retrieval_scopes from public;
revoke all on legal.retrieval_indexes from public;

do $block$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on legal.domains from anon';
    execute 'revoke all on legal.source_kinds from anon';
    execute 'revoke all on legal.document_types from anon';
    execute 'revoke all on legal.legal_unit_types from anon';
    execute 'revoke all on legal.document_domains from anon';
    execute 'revoke all on legal.corpus_version_domains from anon';
    execute 'revoke all on legal.retrieval_scopes from anon';
    execute 'revoke all on legal.retrieval_indexes from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on legal.domains from authenticated';
    execute 'revoke all on legal.source_kinds from authenticated';
    execute 'revoke all on legal.document_types from authenticated';
    execute 'revoke all on legal.legal_unit_types from authenticated';
    execute 'revoke all on legal.document_domains from authenticated';
    execute 'revoke all on legal.corpus_version_domains from authenticated';
    execute 'revoke all on legal.retrieval_scopes from authenticated';
    execute 'revoke all on legal.retrieval_indexes from authenticated';
  end if;
end
$block$;

drop view if exists legal.document_catalog;

create view legal.document_catalog
with (security_invoker = true)
as
select
  d.id as document_id,
  d.title as display_name,
  case
    when d.source_kind = 'legislation' then coalesce(
      substring(d.source_document_id from '^law-([0-9]+)'),
      substring(d.title from '^([0-9]+)[[:space:]]+sayılı')
    )
    else null
  end as document_number,
  case
    when d.source_kind = 'legislation' then coalesce(
      'Kanun No. ' || coalesce(
        substring(d.source_document_id from '^law-([0-9]+)'),
        substring(d.title from '^([0-9]+)[[:space:]]+sayılı')
      ),
      d.title,
      d.source_document_id
    )
    when d.source_kind = 'court_decision' then coalesce(
      nullif(
        concat_ws(
          ' / ',
          case when nullif(d.case_number, '') is not null then 'E. ' || d.case_number end,
          case when nullif(d.decision_number, '') is not null then 'K. ' || d.decision_number end
        ),
        ''
      ),
      d.title,
      d.source_document_id
    )
    else coalesce(d.title, d.source_document_id)
  end as legal_identifier,
  d.source_kind,
  d.document_type,
  dt.display_name as document_category,
  d.domain as domain,
  coalesce(memberships.domains, '[]'::jsonb) as domains,
  d.authority,
  d.chamber,
  d.case_number,
  d.decision_number,
  d.document_date,
  d.effective_from,
  d.effective_to,
  d.source_name,
  d.source_document_id,
  d.canonical_source_url,
  p.id as current_parse_id,
  p.parser_version,
  p.status as parse_status,
  a.id as artifact_id,
  a.media_type,
  a.storage_path,
  a.content_hash as artifact_hash,
  coalesce(
    array(
      select cvd.corpus_version
      from legal.corpus_version_documents cvd
      where cvd.document_id = d.id
        and cvd.parse_id = d.current_parse_id
      order by cvd.corpus_version
    ),
    '{}'::text[]
  ) as corpus_versions
from legal.documents d
join legal.document_types dt
  on dt.code = d.document_type and dt.source_kind_code = d.source_kind
left join legal.document_parses p
  on p.id = d.current_parse_id and p.document_id = d.id
left join legal.document_artifacts a
  on a.id = p.artifact_id and a.document_id = d.id
left join lateral (
  select jsonb_agg(
    jsonb_build_object(
      'code', dd.domain_code,
      'display_name', domains.display_name,
      'role', dd.role,
      'metadata', dd.metadata
    ) order by dd.domain_code
  ) as domains
  from legal.document_domains dd
  join legal.domains domains on domains.code = dd.domain_code
  where dd.document_id = d.id
) memberships on true;

comment on view legal.document_catalog is
  'Backend-only document catalog with registry labels and multi-domain memberships.';

revoke all on legal.document_catalog from public;

do $block$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on legal.document_catalog from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on legal.document_catalog from authenticated';
  end if;
end
$block$;
