const dateFormatter = new Intl.DateTimeFormat('tr-TR', { day: 'numeric', month: 'long' });
const timeFormatter = new Intl.DateTimeFormat('tr-TR', { hour: '2-digit', minute: '2-digit' });

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** "Bugün, 14:32" / "Dün" / "22 Eylül", relative to `now`. */
export function formatRelativeDay(iso: string, now: number): string {
  const date = new Date(iso);
  const days = Math.round((startOfDay(new Date(now)) - startOfDay(date)) / 86_400_000);
  if (days <= 0) return `Bugün, ${timeFormatter.format(date)}`;
  if (days === 1) return 'Dün';
  return dateFormatter.format(date);
}

export function historyGroup(iso: string, now: number): 'Bugün' | 'Önceki 7 gün' | 'Daha eski' {
  const days = Math.round((startOfDay(new Date(now)) - startOfDay(new Date(iso))) / 86_400_000);
  if (days <= 0) return 'Bugün';
  if (days <= 7) return 'Önceki 7 gün';
  return 'Daha eski';
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} MB`;
}

export function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function formatSeconds(ms: number | null): string | null {
  if (ms === null) return null;
  return `${Math.max(1, Math.round(ms / 1000))} sn`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : name.slice(0, 2);
  return letters.toLocaleUpperCase('tr-TR');
}

const MESSAGES: Record<string, string> = {
  authentication_required: 'Oturumunuzun süresi doldu. Lütfen yeniden giriş yapın.',
  invalid_access_token: 'Oturumunuzun süresi doldu. Lütfen yeniden giriş yapın.',
  network_unreachable: 'Sunucuya ulaşılamıyor. Bağlantınızı ya da API adresini kontrol edin.',
  data_service_unavailable: 'Veri servisi geçici olarak kullanılamıyor.',
  chat_capacity_exceeded: 'Aynı anda en fazla iki soru işlenebilir. Birinin bitmesini bekleyin.',
  conversation_not_found: 'Sohbet bulunamadı.',
  case_not_found: 'Dava bulunamadı.',
  generation_not_found: 'Cevap kaydı bulunamadı.',
  file_not_found: 'Dosya bulunamadı.',
  generation_not_cancellable: 'Bu cevap artık iptal edilemiyor.',
  conversation_domain_mismatch: 'Bu sohbet farklı bir hukuk alanına ait.',
  conversation_case_mismatch: 'Bu sohbet başka bir davaya bağlı.',
  validation_failed: 'Gönderilen bilgiler geçersiz.',
  retrieval_index_not_ready: 'Arama servisi şu an hazır değil. Biraz sonra tekrar deneyin.',
  search_capacity_exceeded: 'Önceki aramanız sürüyor; birkaç saniye sonra tekrar deneyin.',
  file_too_large: 'Dosya 50 MB sınırını aşıyor.',
  user_file_quota_exceeded: 'Depolama kotanız doldu. Yer açmak için dosya silin.',
  upload_intent_expired: 'Yükleme süresi doldu; dosyayı yeniden yükleyin.',
  file_not_ready: 'Dosya henüz hazır değil.',
  file_not_completable: 'Bu dosyanın yüklemesi tamamlanamıyor.',
  storage_temporarily_unavailable: 'Depolama servisi geçici olarak kullanılamıyor.',
  provider_temporarily_unavailable: 'Dil modeli servisi geçici olarak yanıt vermiyor.',
  model_temporarily_unavailable: 'Arama modeli servisi geçici olarak yanıt vermiyor.',
  citation_integrity_failed: 'Atıflar kaynaklarla eşleşmediği için cevap reddedildi.',
  job_failed: 'Cevap oluşturulamadı.',
  invalid_pdf_signature: 'Dosya geçerli bir PDF değil.',
  invalid_text_file: 'Metin dosyası ikili veri içeriyor.',
  invalid_text_encoding: 'Metin dosyasının karakter kodlaması okunamadı; UTF-8 olarak kaydedin.',
  unsupported_media_type: 'Desteklenmeyen dosya türü. PDF, Word (DOCX) veya TXT yükleyin.',
  file_size_mismatch: 'Yüklenen dosyanın boyutu beyan edilenle eşleşmiyor.',
  invalid_docx: 'Dosya geçerli bir Word (DOCX) belgesi değil.',
  scanned_pdf_not_supported: 'Taranmış PDF desteklenmiyor: sayfalarda okunabilir metin yok.',
  encrypted_pdf: 'PDF parola korumalı. Korumasız bir kopyasını yükleyin.',
  unreadable_pdf: 'PDF okunamadı; dosya bozuk olabilir.',
  empty_document: 'Belgede okunabilir metin bulunamadı.',
  too_many_pages: 'Belge çok uzun; daha küçük parçalara bölüp yükleyin.',
  document_too_large: 'Belgenin metni işlenemeyecek kadar büyük.',
  file_content_changed: 'Dosya içeriği doğrulanan sürümle eşleşmiyor; yeniden yükleyin.',
  vector_store_temporarily_unavailable: 'Arama dizini geçici olarak kullanılamıyor.',
  file_not_reindexable: 'Bu dosya yeniden işlenemez; dosyayı yeniden yükleyin.',
  files_processing: 'Dosyalar işleniyor; tamamlanınca soru sorabilirsiniz.',
  web_search_unavailable: 'Web araması şu an kullanılamıyor.',
  web_search_quota_exceeded: 'Bu ayın web araması hakkı doldu; ay başında yenilenir.',
  web_search_temporarily_unavailable: 'Web araması servisi geçici olarak yanıt vermiyor.',
  web_search_failed: 'Web araması tamamlanamadı.',
  analysis_requires_case: 'Dosya analizi yalnızca bir davanın dosyaları için yapılabilir.',
  case_has_no_ready_files: 'Analiz için davada işlenmesi tamamlanmış en az bir dosya olmalı.',
};

const VERIFICATION_FAILURES = new Set([
  'invalid_structured_output',
  'invalid_support_output',
  'incomplete_support_output',
  'invalid_source_id',
  'duplicate_claim_id',
  'unexpected_doctrine_answer',
  'generation_failed',
]);

export function describeError(error: unknown): string {
  const code =
    typeof error === 'string'
      ? error
      : error && typeof error === 'object' && 'code' in error
        ? String((error as { code: unknown }).code)
        : '';
  if (VERIFICATION_FAILURES.has(code)) {
    return 'Model çıktısı güvenli biçimde doğrulanamadığı için cevap gösterilmedi.';
  }
  return MESSAGES[code] ?? 'Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.';
}

/** Indexing failures a new attempt can fix; format errors (a scanned PDF…) cannot. */
export function isRetryableIngestFailure(code: string | null): boolean {
  return (
    code === 'model_temporarily_unavailable' ||
    code === 'storage_temporarily_unavailable' ||
    code === 'vector_store_temporarily_unavailable' ||
    code === 'job_failed'
  );
}

/** Transient failures are worth a retry; validation failures would fail the same way. */
export function isRetryableFailure(code: string | null): boolean {
  return (
    code === 'provider_temporarily_unavailable' ||
    code === 'model_temporarily_unavailable' ||
    code === 'storage_temporarily_unavailable' ||
    code === 'web_search_temporarily_unavailable' ||
    code === 'job_failed' ||
    (code !== null && VERIFICATION_FAILURES.has(code))
  );
}
