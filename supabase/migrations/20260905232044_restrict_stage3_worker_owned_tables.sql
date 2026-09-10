-- Generations and citation snapshots are produced exclusively by the trusted
-- FastAPI/worker path.  Keep them readable through their ownership RLS policies,
-- but do not let browser roles manufacture or alter verified AI output.
revoke insert, update, delete, truncate, references, trigger
  on public.chat_generations, public.message_citations
  from anon, authenticated;

-- Supabase projects grant broad privileges to frontend roles through default
-- privileges.  Reassert the intended read-only contract for existing objects.
grant select on public.chat_generations, public.message_citations to authenticated;
