// Mirrors the FastAPI responses in backend/app/api and backend/app/core/repository.py.

export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type GenerationStage = 'retrieving' | 'generating' | 'verifying';
export type AnswerStatus = 'answered' | 'insufficient_evidence';
export type SourceChannel = 'primary' | 'doctrine' | 'file' | 'web';
export type SourceScope = 'global' | 'private' | 'web';
/**
 * corpus: the legal corpus and the user's files; web: the same plus a labelled web section;
 * analysis: a report over every ready file of a case (the case page's button).
 */
export type SearchMode = 'corpus' | 'web' | 'analysis';

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

/**
 * Global snapshots point into the legal corpus, private ones into the user's own file,
 * web ones at a page a web search found (the excerpt is kept as it was at search time).
 */
export interface SourceSnapshot {
  source_id: string;
  document_id: string | null;
  parse_id: string | null;
  chunk_id: string | null;
  source_scope: SourceScope;
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
  corpus_version: string | null;
  retrieval_scope_version: string | null;
  index_version: string;
  file_id?: string;
  file_chunk_id?: string;
  section_title?: string | null;
  location_label?: string;
  /** Set once the file was deleted: the passage and file name are gone. */
  redacted?: boolean;
  site?: string;
  published_date?: string | null;
  retrieved_on?: string;
  /** Law passages only: the official amendment notes of the articles it covers, newest first. */
  provision_changes?: ProvisionChange[];
  /** Decisions only: changes, after the decision, to the articles it rests on. */
  cited_provision_changes?: ProvisionChange[];
}

export type ProvisionChangeType = 'added' | 'amended' | 'repealed' | 'annulled';

export interface ProvisionChange {
  event_type: ProvisionChangeType;
  /** The amending law's adoption date (for an annulment, the court's decision date). */
  change_date: string;
  effective_from: string | null;
  amending_law: string | null;
  /** e.g. "m.3, 12. fıkra"; empty when the note is not tied to an article. */
  provision: string;
  /** The official note as the law text prints it. */
  annotation: string;
}

/**
 * Yürürlük kontrolü: a cited provision changed after the case date (changed_after) or
 * shortly before it, so its effective date needs checking (near_change); or a cited
 * decision rests on an article that changed after it was decided (decision_outdated).
 */
export interface TemporalCheck extends ProvisionChange {
  source_id: string;
  level: 'changed_after' | 'near_change' | 'decision_outdated';
  title: string;
  /** decision_outdated only. */
  decision_date?: string;
  /** Null for a decision checked without a case date. */
  case_date: string | null;
  case_date_label: string | null;
  text: string;
}

/** Why a web search could help: nothing found, a provision changed, or something missing. */
export type WebSearchOfferReason = 'no_sources' | 'provision_changed' | 'missing_info';

export interface Citation {
  claim_id: string;
  source_id: string;
  source_scope: SourceScope;
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

/** Answers written before the conversational format: separate claim lists per source kind. */
export interface LegacyAnswer {
  format?: undefined;
  answer_status: AnswerStatus;
  /** Absent on answers produced before users could upload files. */
  file_answer?: AnswerSection | null;
  primary_answer: AnswerSection | null;
  doctrine_answer: AnswerSection | null;
  limitations: string[];
}

/**
 * verified/partial: at least one cited source passed verification.
 * unverified: its sources failed verification, or it states a specific rule, period
 * or amount without a source. plain: explanation that needs no source.
 */
export type SentenceVerification = 'verified' | 'partial' | 'unverified' | 'plain';

export interface AnswerSentence {
  id: string;
  text: string;
  source_ids: string[];
  verification: SentenceVerification;
}

export interface AnswerBlock {
  kind: 'paragraph' | 'heading' | 'bullets';
  sentences: AnswerSentence[];
}

export interface ConversationalAnswer {
  format: 'conversational-v1';
  answer_status: AnswerStatus;
  blocks: AnswerBlock[];
  limitations: string[];
  unverified_count: number;
  /** Absent on answers written before web search existed (they are corpus answers). */
  search_mode?: SearchMode;
  /** With web search on: what web pages confirm, add or contradict, shown after the answer. */
  web_blocks?: AnswerBlock[];
  /** found, empty, or why the web search failed; null without one. */
  web_search_status?: string | null;
  /** A web search could help this legal question; the user may run it. */
  web_search_offered?: boolean;
  /** Why; absent on answers from before the reasons existed (they meant no_sources). */
  web_search_offer?: WebSearchOfferReason | null;
  /** Absent on answers written before the check existed. */
  temporal_checks?: TemporalCheck[];
  /** A cited decision explains a provision repealed since; shown above the answer. */
  repeal_notice?: string | null;
  /** Deep research only: the parts researched and how much was read. */
  research?: ResearchSummary;
}

export interface ResearchSummary {
  parts: { question: string; sources: number }[];
  searches: number;
  follow_ups: number;
  /** Articles looked up because the found decisions rest on them, e.g. "4857 m.20". */
  followed_articles: string[];
  passages: number;
}

export type StructuredAnswer = LegacyAnswer | ConversationalAnswer;

export interface GenerationSummary {
  id: string;
  user_message_id: string;
  assistant_message_id: string | null;
  status: JobStatus;
  stage: GenerationStage | null;
  answer_status: AnswerStatus | null;
  safe_error_code: string | null;
  include_doctrine: boolean;
  search_mode: SearchMode;
  /** A deep research report rather than a chat answer; absent on older generations. */
  deep_research?: boolean;
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

export interface ChatCapabilities {
  web_search: boolean;
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
