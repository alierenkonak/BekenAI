-- Expose the worker's current pipeline stage so clients can show honest progress
-- (retrieval, drafting, claim verification) instead of a single "processing" state.
alter table public.chat_generations
  add column if not exists stage text;

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'chat_generations_stage_check'
      and conrelid = 'public.chat_generations'::regclass
  ) then
    alter table public.chat_generations
      add constraint chat_generations_stage_check
      check (stage is null or stage in ('retrieving', 'generating', 'verifying'));
  end if;
end
$block$;
