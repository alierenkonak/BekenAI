-- Deep research answers a chat question with several searches and one report. It combines
-- with web search, so it is a flag beside search_mode rather than a mode of its own.
alter table public.chat_generations
  add column if not exists deep_research boolean not null default false;
