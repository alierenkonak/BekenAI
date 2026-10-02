-- Doctrine is searched for every question since ADR 0008, so the per-conversation switch
-- this column stored is no longer read or written.
alter table public.conversations drop column if exists doctrine_enabled;
