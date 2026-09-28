-- Web search fallback: when the legal corpus has no source for a question, the user may
-- ask for a web search. The generation records which search answered it, and its
-- citations form a third scope that points at no corpus or file row: the snapshot keeps
-- the page URL and the excerpt the verifier checked the sentence against.

alter table public.chat_generations
  add column if not exists search_mode text not null default 'corpus';

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'chat_generations_search_mode_check'
      and conrelid = 'public.chat_generations'::regclass
  ) then
    alter table public.chat_generations
      add constraint chat_generations_search_mode_check
      check (search_mode in ('corpus', 'web'));
  end if;
end
$block$;

alter table public.message_citations
  drop constraint if exists message_citations_source_scope_check;
alter table public.message_citations
  add constraint message_citations_source_scope_check
  check (source_scope in ('global', 'private', 'web'));

alter table public.message_citations
  drop constraint if exists message_citations_source_channel_check;
alter table public.message_citations
  add constraint message_citations_source_channel_check
  check (source_channel in ('primary', 'doctrine', 'file', 'web'));

alter table public.message_citations
  drop constraint if exists message_citations_scope_reference_check;
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
    or (
      source_scope = 'web'
      and source_channel = 'web'
      and document_id is null and parse_id is null and chunk_id is null
      and file_id is null and file_chunk_id is null
    )
  );
