-- Keep the private durable queue explicitly inaccessible even if a frontend role
-- accidentally receives schema/table grants in a future migration.
drop policy if exists jobs_deny_frontend on app_private.jobs;
create policy jobs_deny_frontend on app_private.jobs
  for all to anon, authenticated
  using (false)
  with check (false);

-- Cover every Stage 3 foreign key in its declared column order. Besides satisfying
-- the advisor, these indexes keep cascades and ownership joins predictable as chat
-- history grows.
create index if not exists conversations_domain_code_idx
  on public.conversations (domain_code);
create index if not exists messages_workspace_id_idx
  on public.messages (workspace_id);
create index if not exists messages_conversation_workspace_idx
  on public.messages (conversation_id, workspace_id);
create index if not exists chat_generations_workspace_id_idx
  on public.chat_generations (workspace_id);
create index if not exists chat_generations_conversation_workspace_idx
  on public.chat_generations (conversation_id, workspace_id);
create index if not exists chat_generations_user_message_conversation_idx
  on public.chat_generations (user_message_id, conversation_id);
create index if not exists chat_generations_assistant_message_idx
  on public.chat_generations (assistant_message_id)
  where assistant_message_id is not null;
create index if not exists message_citations_workspace_id_idx
  on public.message_citations (workspace_id);
create index if not exists message_citations_message_conversation_idx
  on public.message_citations (message_id, conversation_id);
create index if not exists message_citations_document_id_idx
  on public.message_citations (document_id);
create index if not exists message_citations_parse_id_idx
  on public.message_citations (parse_id);
create index if not exists message_citations_chunk_id_idx
  on public.message_citations (chunk_id);
create index if not exists user_files_case_workspace_idx
  on public.user_files (case_id, workspace_id);
create index if not exists user_files_uploader_idx
  on public.user_files (uploader_user_id);
