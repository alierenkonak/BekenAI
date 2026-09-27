import { CASE_FILE_MAX_BYTES } from './config';
import { describeError, formatBytes } from './format';
import type { FileMediaType, UserFile } from './types';

export const DOCX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
export const FILE_ACCEPT = `.pdf,.docx,.txt,application/pdf,text/plain,${DOCX_TYPE}`;

// The worker moves these on its own; lists follow them until they settle.
export const TRANSIENT_STATUSES = new Set<UserFile['status']>(['verifying', 'uploaded', 'indexing', 'delete_pending']);
// A chat cannot be asked anything while one of its files is in these (the API answers 409).
export const PROCESSING_STATUSES = new Set<UserFile['status']>(['verifying', 'uploaded', 'indexing']);

export const SAMPLE_FILE_URL = '/ornek/ornek-ise-iade-dosyasi.pdf';
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
export function uploadProblem(file: File): string | null {
  if (file.name.toLowerCase().endsWith('.doc')) {
    return 'Eski Word (.doc) biçimi desteklenmiyor; belgeyi DOCX olarak kaydedip yükleyin.';
  }
  if (!mediaTypeOf(file)) return 'Yalnızca PDF, Word (DOCX) ve TXT dosyaları yüklenebilir.';
  if (file.size > CASE_FILE_MAX_BYTES) return 'Dosya 50 MB sınırını aşıyor.';
  if (file.size === 0) return 'Dosya boş.';
  return null;
}

export function indexingProgress(file: UserFile): string {
  return file.chunks_total ? `${file.chunks_done ?? 0}/${file.chunks_total} parça işlendi` : 'metin çıkarılıyor';
}

export function fileDetail(file: UserFile): string {
  if (file.status === 'failed') return describeError(file.safe_error_code ?? 'job_failed');
  const parts = [formatBytes(file.verified_size_bytes ?? file.expected_size_bytes)];
  if (file.status === 'indexing') {
    parts.push(indexingProgress(file));
  } else if (file.status === 'ready') {
    if (file.page_count) parts.push(`${file.page_count} sayfa`);
    if (file.unreadable_page_count) parts.push(`${file.unreadable_page_count} sayfa okunamadı`);
  }
  return parts.join(' · ');
}
