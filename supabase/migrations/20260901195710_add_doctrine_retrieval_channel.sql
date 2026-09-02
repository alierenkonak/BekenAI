-- Add optional doctrine metadata and independent retrieval channels without rewriting V4.

alter table legal.documents
  add column if not exists author text,
  add column if not exists publication_year integer,
  add column if not exists citation_text text,
  add column if not exists rights_basis text;

alter table legal.documents
  drop constraint if exists documents_publication_year_check;
alter table legal.documents
  add constraint documents_publication_year_check
  check (publication_year is null or publication_year between 1000 and 9999);

insert into legal.source_kinds (code, display_name, metadata)
values (
  'doctrine',
  'Doktrin / Yardımcı Kaynak',
  '{"binding_authority": false}'::jsonb
)
on conflict (code) do update
set display_name = excluded.display_name,
    metadata = excluded.metadata;

insert into legal.document_types (code, source_kind_code, display_name, metadata)
values (
  'course_note',
  'doctrine',
  'Ders Notu / Yardımcı Kaynak',
  '{"binding_authority": false}'::jsonb
)
on conflict (code) do update
set source_kind_code = excluded.source_kind_code,
    display_name = excluded.display_name,
    metadata = excluded.metadata;

alter table legal.retrieval_scopes
  add column if not exists channel text not null default 'primary';
alter table legal.retrieval_scopes
  drop constraint if exists retrieval_scopes_channel_check;
alter table legal.retrieval_scopes
  add constraint retrieval_scopes_channel_check
  check (channel ~ '^[a-z][a-z0-9_]{1,63}$');

alter table legal.retrieval_indexes
  add column if not exists channel text not null default 'primary';
alter table legal.retrieval_indexes
  drop constraint if exists retrieval_indexes_channel_check;
alter table legal.retrieval_indexes
  add constraint retrieval_indexes_channel_check
  check (channel ~ '^[a-z][a-z0-9_]{1,63}$');

alter table legal.retrieval_indexes
  drop constraint if exists retrieval_indexes_domain_code_backend_index_version_key;
alter table legal.retrieval_indexes
  drop constraint if exists retrieval_indexes_domain_channel_backend_version_key;
alter table legal.retrieval_indexes
  add constraint retrieval_indexes_domain_channel_backend_version_key
  unique (domain_code, channel, backend, index_version);

create index if not exists retrieval_scopes_domain_channel_status_idx
  on legal.retrieval_scopes (domain_code, channel, status);
create index if not exists retrieval_indexes_domain_channel_status_idx
  on legal.retrieval_indexes (domain_code, channel, status);

comment on column legal.documents.rights_basis is
  'Backend-only statement of the verified acquisition/use basis; never a public access policy.';
comment on column legal.retrieval_scopes.channel is
  'Independent retrieval lane such as primary or doctrine.';
comment on column legal.retrieval_indexes.channel is
  'Retrieval lane isolated from other indexes in the same legal domain.';
