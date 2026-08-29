-- Keep immutable artifact paths technical while exposing readable legal identifiers.

update legal.documents
set
  title = concat_ws(
    ', ',
    nullif(concat_ws(' ', nullif(authority, ''), nullif(chamber, '')), ''),
    case when nullif(case_number, '') is not null then 'E. ' || case_number end,
    case when nullif(decision_number, '') is not null then 'K. ' || decision_number end
  ),
  updated_at = now()
where source_kind = 'court_decision'
  and title is distinct from concat_ws(
    ', ',
    nullif(concat_ws(' ', nullif(authority, ''), nullif(chamber, '')), ''),
    case when nullif(case_number, '') is not null then 'E. ' || case_number end,
    case when nullif(decision_number, '') is not null then 'K. ' || decision_number end
  );

create or replace view legal.document_catalog
with (security_invoker = true)
as
select
  d.id as document_id,
  d.title as display_name,
  case
    when d.source_kind = 'legislation' then coalesce(
      substring(d.source_document_id from '^law-([0-9]+)'),
      substring(d.title from '^([0-9]+)[[:space:]]+sayılı')
    )
    else null
  end as document_number,
  case
    when d.source_kind = 'legislation' then coalesce(
      'Kanun No. ' || coalesce(
        substring(d.source_document_id from '^law-([0-9]+)'),
        substring(d.title from '^([0-9]+)[[:space:]]+sayılı')
      ),
      d.title,
      d.source_document_id
    )
    when d.source_kind = 'court_decision' then coalesce(
      nullif(
        concat_ws(
          ' / ',
          case when nullif(d.case_number, '') is not null then 'E. ' || d.case_number end,
          case when nullif(d.decision_number, '') is not null then 'K. ' || d.decision_number end
        ),
        ''
      ),
      d.title,
      d.source_document_id
    )
    else coalesce(d.title, d.source_document_id)
  end as legal_identifier,
  d.source_kind,
  d.document_type,
  d.domain,
  d.authority,
  d.chamber,
  d.case_number,
  d.decision_number,
  d.document_date,
  d.effective_from,
  d.effective_to,
  d.source_name,
  d.source_document_id,
  d.canonical_source_url,
  p.id as current_parse_id,
  p.parser_version,
  p.status as parse_status,
  a.id as artifact_id,
  a.media_type,
  a.storage_path,
  a.content_hash as artifact_hash,
  coalesce(
    array(
      select cvd.corpus_version
      from legal.corpus_version_documents cvd
      where cvd.document_id = d.id
        and cvd.parse_id = d.current_parse_id
      order by cvd.corpus_version
    ),
    '{}'::text[]
  ) as corpus_versions
from legal.documents d
left join legal.document_parses p
  on p.id = d.current_parse_id
 and p.document_id = d.id
left join legal.document_artifacts a
  on a.id = p.artifact_id
 and a.document_id = d.id;

comment on view legal.document_catalog is
  'Backend-only readable catalog for documents, current parses, immutable artifacts, and pinned corpus versions.';

revoke all on legal.document_catalog from public;

do $block$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on legal.document_catalog from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on legal.document_catalog from authenticated';
  end if;
end
$block$;
