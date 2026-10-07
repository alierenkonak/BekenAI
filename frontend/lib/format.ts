import type { Messages } from './i18n';

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** "Bugün, 14:32" / "Dün" / "22 Eylül" (or the English equivalents), relative to `now`. */
export function formatRelativeDay(iso: string, now: number, m: Messages): string {
  const date = new Date(iso);
  const days = Math.round((startOfDay(new Date(now)) - startOfDay(date)) / 86_400_000);
  if (days <= 0) return m.format.today(new Intl.DateTimeFormat(m.intl, { hour: '2-digit', minute: '2-digit' }).format(date));
  if (days === 1) return m.format.yesterday;
  return new Intl.DateTimeFormat(m.intl, { day: 'numeric', month: 'long' }).format(date);
}

export function historyGroup(iso: string, now: number): 'today' | 'week' | 'older' {
  const days = Math.round((startOfDay(new Date(now)) - startOfDay(new Date(iso))) / 86_400_000);
  if (days <= 0) return 'today';
  if (days <= 7) return 'week';
  return 'older';
}

export function formatBytes(bytes: number, m: Messages): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString(m.intl, { maximumFractionDigits: 1 })} MB`;
}

export function formatDate(iso: string, m: Messages): string {
  return new Date(iso).toLocaleDateString(m.intl);
}

export function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function formatSeconds(ms: number | null, m: Messages): string | null {
  if (ms === null) return null;
  return m.format.seconds(Math.max(1, Math.round(ms / 1000)));
}

export function initials(name: string, m: Messages): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : name.slice(0, 2);
  return letters.toLocaleUpperCase(m.intl);
}


const VERIFICATION_FAILURES = new Set([
  'invalid_structured_output',
  'invalid_support_output',
  'incomplete_support_output',
  'invalid_source_id',
  'duplicate_claim_id',
  'unexpected_doctrine_answer',
  'generation_failed',
]);

export function describeError(error: unknown, m: Messages): string {
  const code =
    typeof error === 'string'
      ? error
      : error && typeof error === 'object' && 'code' in error
        ? String((error as { code: unknown }).code)
        : '';
  if (VERIFICATION_FAILURES.has(code)) {
    return m.errorVerification;
  }
  return m.errors[code] ?? m.errorFallback;
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
