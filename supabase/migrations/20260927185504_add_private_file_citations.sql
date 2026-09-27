-- Stage 4: answers may cite passages of the user's own files. A citation is either a
-- global corpus chunk (document/parse/chunk) or a private file chunk (file/file chunk),
-- never a mix. Private chunks are deleted with their file, so file_chunk_id carries
-- no foreign key; the snapshot is redacted by the deletion job instead.

alter table public.message_citations
  alter column document_id drop not null,
  alter column parse_id drop not null,
  alter column chunk_id drop not null,
  add column if not exists file_id uuid references public.user_files(id) on delete set null,
  add column if not exists file_chunk_id uuid;

create index if not exists message_citations_file_id_idx
  on public.message_citations (file_id)
  where file_id is not null;

alter table public.message_citations
  drop constraint if exists message_citations_source_channel_check;
alter table public.message_citations
  add constraint message_citations_source_channel_check
  check (source_channel in ('primary', 'doctrine', 'file'));

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'message_citations_scope_reference_check'
      and conrelid = 'public.message_citations'::regclass
  ) then
    alter table public.message_citations
      add constraint message_citations_scope_reference_check check (
        (
          source_scope = 'global'
          and source_channel in ('primary', 'doctrine')
          and document_id is not null and parse_id is not null and chunk_id is not null
          and file_id is null and file_chunk_id is null
        )
        or (
          source_scope = 'private'
          and source_channel = 'file'
          and document_id is null and parse_id is null and chunk_id is null
          and file_chunk_id is not null
        )
      );
  end if;
end
$block$;
