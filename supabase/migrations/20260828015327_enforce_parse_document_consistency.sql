do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'document_artifacts_id_document_id_key'
      and conrelid = 'legal.document_artifacts'::regclass
  ) then
    alter table legal.document_artifacts
      add constraint document_artifacts_id_document_id_key unique (id, document_id);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'document_chunks_id_parse_id_key'
      and conrelid = 'legal.document_chunks'::regclass
  ) then
    alter table legal.document_chunks
      add constraint document_chunks_id_parse_id_key unique (id, parse_id);
  end if;
end
$block$;

alter table legal.document_parses
  drop constraint if exists document_parses_artifact_id_fkey;
alter table legal.document_parses
  add constraint document_parses_artifact_document_fkey
  foreign key (artifact_id, document_id)
  references legal.document_artifacts(id, document_id) on delete restrict;

alter table legal.documents
  drop constraint if exists documents_current_parse_id_fkey;
alter table legal.documents
  add constraint documents_current_parse_document_fkey
  foreign key (current_parse_id, id)
  references legal.document_parses(id, document_id) on delete restrict;

alter table legal.document_chunks
  drop constraint if exists document_chunks_parse_id_fkey;
alter table legal.document_chunks
  add constraint document_chunks_parse_document_fkey
  foreign key (parse_id, document_id)
  references legal.document_parses(id, document_id) on delete cascade;

alter table legal.corpus_version_documents
  drop constraint if exists corpus_version_documents_parse_id_fkey;
alter table legal.corpus_version_documents
  add constraint corpus_version_documents_parse_document_fkey
  foreign key (parse_id, document_id)
  references legal.document_parses(id, document_id) on delete restrict;

alter table legal.legal_units
  drop constraint if exists legal_units_parent_unit_id_fkey;
alter table legal.legal_units
  add constraint legal_units_parent_parse_fkey
  foreign key (parent_unit_id, parse_id)
  references legal.legal_units(id, parse_id) on delete cascade;

alter table legal.provision_events
  drop constraint if exists provision_events_legal_unit_id_fkey;
alter table legal.provision_events
  add constraint provision_events_unit_parse_fkey
  foreign key (legal_unit_id, parse_id)
  references legal.legal_units(id, parse_id) on delete cascade;

alter table legal.chunk_legal_units add column if not exists parse_id uuid;

update legal.chunk_legal_units clu
set parse_id = c.parse_id
from legal.document_chunks c
where c.id = clu.chunk_id and clu.parse_id is null;

alter table legal.chunk_legal_units alter column parse_id set not null;
alter table legal.chunk_legal_units
  drop constraint if exists chunk_legal_units_chunk_id_fkey;
alter table legal.chunk_legal_units
  drop constraint if exists chunk_legal_units_legal_unit_id_fkey;
alter table legal.chunk_legal_units
  add constraint chunk_legal_units_chunk_parse_fkey
  foreign key (chunk_id, parse_id)
  references legal.document_chunks(id, parse_id) on delete cascade;
alter table legal.chunk_legal_units
  add constraint chunk_legal_units_unit_parse_fkey
  foreign key (legal_unit_id, parse_id)
  references legal.legal_units(id, parse_id) on delete cascade;

alter table legal.provision_versions
  drop constraint if exists provision_versions_source_artifact_id_fkey;
alter table legal.provision_versions
  add constraint provision_versions_artifact_document_fkey
  foreign key (source_artifact_id, document_id)
  references legal.document_artifacts(id, document_id) on delete restrict;

create index if not exists document_parses_artifact_document_idx
  on legal.document_parses (artifact_id, document_id);
create index if not exists chunk_legal_units_parse_id_idx
  on legal.chunk_legal_units (parse_id);
