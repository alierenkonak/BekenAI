import { CASE_FILE_MAX_BYTES } from './config';
import { describeError, formatBytes } from './format';
import type { Messages } from './i18n';
import type { FileMediaType, UserFile } from './types';

export const DOCX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
export const FILE_ACCEPT = `.pdf,.docx,.txt,application/pdf,text/plain,${DOCX_TYPE}`;

// The worker moves these on its own; lists follow them until they settle.
export const TRANSIENT_STATUSES = new Set<UserFile['status']>(['verifying', 'uploaded', 'indexing', 'delete_pending']);
// A chat cannot be asked anything while one of its files is in these (the API answers 409).
export const PROCESSING_STATUSES = new Set<UserFile['status']>(['verifying', 'uploaded', 'indexing']);

export const SAMPLE_FILE_URL = '/ornek/ornek-ise-iade-dosyasi.pdf';
// Sent to the backend as typed, so they stay in Turkish in both interface languages.
export const SAMPLE_QUESTIONS = [
  'İşveren fesih gerekçesi olarak ne göstermiş?',
  'Fesihten önce işçinin savunması alınmış mı? Bu fesih geçerli mi?',
  'Arabuluculuk süreci ne zaman başlamış ve nasıl sonuçlanmış?',
  'Davacı hangi alacakları talep ediyor?',
];

export function mediaTypeOf(file: File): FileMediaType | null {
  const name = file.name.toLowerCase();
  if (file.type === 'application/pdf' || name.endsWith('.pdf')) return 'application/pdf';
  if (file.type === DOCX_TYPE || name.endsWith('.docx')) return DOCX_TYPE;
  if (file.type === 'text/plain' || name.endsWith('.txt')) return 'text/plain';
  return null;
}

/** Why a file cannot be uploaded, checked before any request is made. */
export function uploadProblem(file: File, m: Messages): string | null {
  if (file.name.toLowerCase().endsWith('.doc')) return m.files.legacyDoc;
  if (!mediaTypeOf(file)) return m.files.unsupported;
  if (file.size > CASE_FILE_MAX_BYTES) return m.files.tooLarge;
  if (file.size === 0) return m.files.empty;
  return null;
}

export function indexingProgress(file: UserFile, m: Messages): string {
  return file.chunks_total ? m.files.chunks(file.chunks_done ?? 0, file.chunks_total) : m.files.extracting;
}

export function fileDetail(file: UserFile, m: Messages): string {
  if (file.status === 'failed') return describeError(file.safe_error_code ?? 'job_failed', m);
  const parts = [formatBytes(file.verified_size_bytes ?? file.expected_size_bytes, m)];
  if (file.status === 'indexing') {
    parts.push(indexingProgress(file, m));
  } else if (file.status === 'ready') {
    if (file.page_count) parts.push(m.files.pages(file.page_count));
    if (file.unreadable_page_count) parts.push(m.files.unreadablePages(file.unreadable_page_count));
  }
  return parts.join(' · ');
}
