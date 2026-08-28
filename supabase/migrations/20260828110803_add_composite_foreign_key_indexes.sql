create index if not exists chunk_legal_units_chunk_parse_idx
  on legal.chunk_legal_units (chunk_id, parse_id);

create index if not exists chunk_legal_units_unit_parse_idx
  on legal.chunk_legal_units (legal_unit_id, parse_id);

create index if not exists corpus_version_documents_parse_document_idx
  on legal.corpus_version_documents (parse_id, document_id);

create index if not exists document_chunks_parse_document_idx
  on legal.document_chunks (parse_id, document_id);

create index if not exists documents_current_parse_document_idx
  on legal.documents (current_parse_id, id);

create index if not exists legal_units_parent_parse_idx
  on legal.legal_units (parent_unit_id, parse_id);

create index if not exists provision_events_unit_parse_idx
  on legal.provision_events (legal_unit_id, parse_id);

create index if not exists provision_versions_artifact_document_idx
  on legal.provision_versions (source_artifact_id, document_id);
