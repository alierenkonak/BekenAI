-- File metadata is created and transitioned only by the trusted FastAPI/worker
-- database connection. Browser roles need owner-scoped reads so Storage RLS can
-- validate upload intents, but must not bypass quota, verification, or deletion.
revoke insert, update, delete, truncate, references, trigger
  on public.user_files
  from anon, authenticated;

-- Both parent foreign keys use ON DELETE CASCADE. Prevent browser roles from
-- deleting a case/workspace to bypass the child-table revoke. FastAPI archives
-- cases and trusted account cleanup continues to use the backend DB role.
revoke delete, truncate
  on public.cases, public.workspaces
  from anon, authenticated;

grant select on public.user_files to authenticated;

drop policy if exists user_files_workspace_owner_all on public.user_files;
drop policy if exists user_files_workspace_owner_select on public.user_files;
create policy user_files_workspace_owner_select on public.user_files
  for select to authenticated
  using (
    uploader_user_id = (select auth.uid())
    and exists (
      select 1 from public.workspaces w
      where w.id = user_files.workspace_id
        and w.owner_user_id = (select auth.uid())
    )
  );
