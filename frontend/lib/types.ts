// Mirrors the FastAPI responses in backend/app/api and backend/app/core/repository.py.

export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type GenerationStage = 'retrieving' | 'generating' | 'verifying';
export type AnswerStatus = 'answered' | 'insufficient_evidence';
export type SourceChannel = 'primary' | 'doctrine';

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface LegalCase {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  workspace_id: string;
  case_id: string | null;
  title: string;
  domain_code: string;
  doctrine_enabled: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceSnapshot {
  source_id: string;
  document_id: string;
  parse_id: string;
  chunk_id: string;
  source_scope: 'global' | 'private';
  source_channel: SourceChannel;
  title: string;
  authority: string | null;
  decision_metadata: {
    chamber: string | null;
    case_number: string | null;
    decision_number: string | null;
    document_date: string | null;
  };
  page_number: number | null;
  breadcrumb: string[];
  exact_passage: string;
  source_url: string | null;
  corpus_version: string;
  retrieval_scope_version: string;
  index_version: string;
}

export interface Citation {
  claim_id: string;
  source_id: string;
  source_scope: 'global' | 'private';
  source_channel: SourceChannel;
  source_snapshot: SourceSnapshot;
  integrity_status: 'valid';
  support_status: 'supported' | 'partial';
  support_reason: string | null;
  ordinal: number;
}

export interface Claim {
  claim_id: string;
  text: string;
  source_ids: string[];
}

export interface AnswerSection {
  summary: string;
  claims: Claim[];
}

export interface StructuredAnswer {
  answer_status: AnswerStatus;
  primary_answer: AnswerSection | null;
  doctrine_answer: AnswerSection | null;
  limitations: string[];
}

export interface GenerationSummary {
  id: string;
  user_message_id: string;
  assistant_message_id: string | null;
  status: JobStatus;
  stage: GenerationStage | null;
  answer_status: AnswerStatus | null;
  safe_error_code: string | null;
  include_doctrine: boolean;
  latency_ms: number | null;
  corpus_versions: Record<string, string>;
  index_versions: Record<string, string>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface GenerationDetail extends GenerationSummary {
  conversation_id: string;
  assistant_content: string | null;
  assistant_structured_content: StructuredAnswer | null;
  citations: Citation[];
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  structured_content: StructuredAnswer | null;
  status: JobStatus;
  created_at: string;
  generation: GenerationSummary | null;
  citations?: Citation[];
}

export interface ChatEnqueued {
  generation_id: string;
  conversation_id: string;
  user_message_id: string;
  status: JobStatus;
}

export type FileStatus =
  | 'pending_upload'
  | 'verifying'
  | 'uploaded'
  | 'indexing'
  | 'ready'
  | 'failed'
  | 'delete_pending'
  | 'deleted';

export type FileMediaType =
  | 'application/pdf'
  | 'text/plain'
  | 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

export interface UserFile {
  id: string;
  /** Exactly one of case_id / conversation_id is set while the file is live. */
  case_id: string | null;
  conversation_id: string | null;
  original_name: string;
  storage_bucket: string;
  storage_path: string;
  declared_media_type: FileMediaType;
  expected_size_bytes: number;
  verified_size_bytes: number | null;
  status: FileStatus;
  safe_error_code: string | null;
  page_count: number | null;
  unreadable_page_count: number | null;
  chunks_total: number | null;
  chunks_done: number | null;
  indexed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadIntent {
  file: UserFile;
  upload: { bucket: string; path: string; upsert: false; authorization: 'supabase_user_jwt' };
}

export interface SearchResult {
  source_channel: SourceChannel;
  source_kind: string;
  domain: string;
  rank: number;
  score: number;
  document_id: string;
  chunk_id: string;
  title: string;
  document_type: string;
  authority: string | null;
  chamber: string | null;
  case_number: string | null;
  decision_number: string | null;
  document_date: string | null;
  breadcrumb: string[];
  section_type: string;
  page_number: number | null;
  exact_passage: string;
  source_url: string | null;
  corpus_version: string;
  index_version: string;
  author: string | null;
  publication_year: number | null;
  citation_text: string | null;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  doctrine_results: SearchResult[];
}
