-- Pinned chats stay at the top of the sidebar. Pinning does not touch updated_at, so a
-- chat keeps its place in the history when it is unpinned.
alter table public.conversations add column if not exists pinned_at timestamptz;

create index if not exists conversations_workspace_pinned_idx
  on public.conversations (workspace_id, pinned_at desc)
  where pinned_at is not null;
