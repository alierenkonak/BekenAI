-- Case analysis: a report over every ready file of a case is stored as a chat generation
-- with search_mode 'analysis'. Reading a whole case, it can cite more than 99 file
-- passages, so source ids may carry three digits.

alter table public.chat_generations
  drop constraint if exists chat_generations_search_mode_check;
alter table public.chat_generations
  add constraint chat_generations_search_mode_check
  check (search_mode in ('corpus', 'web', 'analysis'));

alter table public.message_citations
  drop constraint if exists message_citations_source_id_check;
alter table public.message_citations
  add constraint message_citations_source_id_check
  check (source_id ~ '^SOURCE_[A-Z]+_[0-9]{2,3}$');
