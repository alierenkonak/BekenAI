-- Reserve the maximum possible object size until trusted verification succeeds.
-- Failed, pending and expired rows remain charged until Storage deletion completes.
alter table public.user_files
  add column if not exists reserved_size_bytes bigint;

update public.user_files
set reserved_size_bytes = case
  when status = 'uploaded' then greatest(
    expected_size_bytes,
    coalesce(verified_size_bytes, expected_size_bytes)
  )
  else 52428800
end
where reserved_size_bytes is null;

alter table public.user_files
  alter column reserved_size_bytes set default 52428800,
  alter column reserved_size_bytes set not null;

do $block$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'user_files_reserved_size_bytes_check'
      and conrelid = 'public.user_files'::regclass
  ) then
    alter table public.user_files
      add constraint user_files_reserved_size_bytes_check
      check (reserved_size_bytes between expected_size_bytes and 52428800);
  end if;
end
$block$;

-- Reassert the provider-side hard cap as defense in depth.
do $block$
begin
  if to_regclass('storage.buckets') is not null then
    update storage.buckets
    set public = false,
        file_size_limit = 52428800,
        allowed_mime_types = array['application/pdf', 'text/plain']::text[]
    where id = 'case-files';
  end if;
end
$block$;
