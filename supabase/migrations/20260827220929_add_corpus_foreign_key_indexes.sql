create index if not exists document_artifacts_document_id_idx
  on legal.document_artifacts (document_id);
create index if not exists ingestion_runs_corpus_version_idx
  on legal.ingestion_runs (corpus_version);
create index if not exists ingestion_errors_run_id_idx
  on legal.ingestion_errors (run_id);
create index if not exists corpus_version_documents_document_id_idx
  on legal.corpus_version_documents (document_id);
