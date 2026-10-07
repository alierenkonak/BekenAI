'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { Icon, Spinner } from '@/components/icons';
import { api } from '@/lib/api';
import { describeError, formatDate } from '@/lib/format';
import type { Messages } from '@/lib/i18n';
import { useI18n } from '@/lib/i18n/client';
import type { SearchResponse, SearchResult } from '@/lib/types';

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Marks query words (4+ letters, prefix match) so Turkish suffixes still highlight. */
function highlight(text: string, query: string): ReactNode {
  const words = [...new Set(query.toLocaleLowerCase('tr-TR').split(/\s+/).filter((word) => word.length >= 4))];
  if (!words.length) return text;
  const pattern = new RegExp(`(${words.map((word) => escapeRegExp(word.slice(0, Math.max(4, word.length - 2)))).join('|')})`, 'giu');
  return text.split(pattern).map((part, index) =>
    index % 2 === 1 ? (
      <mark key={index} className="rounded-[3px] bg-mark px-0.5 text-fg">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function kindOf(result: SearchResult, m: Messages): { label: string; cls: string } {
  if (result.source_channel === 'doctrine') return { label: m.search.kindDoctrine, cls: 'bg-doc-bg text-doc' };
  if (result.case_number || result.decision_number) return { label: m.search.kindDecision, cls: 'bg-muted text-fg2' };
  return { label: m.search.kindLegislation, cls: 'bg-accent-bg text-accent' };
}

function meta(result: SearchResult, m: Messages): string {
  const parts: string[] = [];
  if (result.author) parts.push(result.author);
  if (result.chamber) parts.push(result.chamber);
  if (result.case_number) parts.push(`E. ${result.case_number}`);
  if (result.decision_number) parts.push(`K. ${result.decision_number}`);
  if (result.document_date) parts.push(formatDate(result.document_date, m));
  if (result.publication_year && !result.document_date) parts.push(String(result.publication_year));
  if (result.page_number) parts.push(m.search.page(result.page_number));
  return parts.join(' · ');
}

function ResultCard({ result, query }: { result: SearchResult; query: string }) {
  const { m } = useI18n();
  const kind = kindOf(result, m);
  const passage = result.exact_passage.length > 700 ? `${result.exact_passage.slice(0, 700)}…` : result.exact_passage;
  return (
    <article className={`flex flex-col gap-2 py-[18px] ${result.source_channel === 'doctrine' ? '' : 'border-b border-line'}`}>
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className={`flex h-[22px] items-center rounded-md px-2 text-xs font-medium ${kind.cls}`}>{kind.label}</span>
        <h2 lang="tr" className="m-0 text-[15px] font-semibold">
          {result.title}
        </h2>
        {result.breadcrumb.length > 0 && <span className="text-[13px] text-fg3">{result.breadcrumb.join(' › ')}</span>}
      </div>
      <p lang="tr" className="m-0 whitespace-pre-line text-sm leading-relaxed text-fg2">
        {highlight(passage, query)}
      </p>
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5">
        <span className="font-mono text-[11.5px] text-fg3">{meta(result, m) || result.corpus_version}</span>
        <span className="grow" />
        <Link
          href={`/sohbet?q=${encodeURIComponent(query)}`}
          className="flex items-center gap-1.5 text-[13px] font-medium text-fg no-underline hover:underline"
        >
          <Icon name="chat" size={14} />
          {m.search.askInChat}
        </Link>
        {result.source_url && (
          <a href={result.source_url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 text-[13px] text-fg2 no-underline hover:text-fg">
            <Icon name="ext" size={14} />
            {m.search.openSource}
          </a>
        )}
      </div>
    </article>
  );
}

export function SourceSearch() {
  const router = useRouter();
  const { m } = useI18n();
  const t = m.search;
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get('q') ?? '';
  const [query, setQuery] = useState(initialQuery);
  // A new object per search, so searching the same text again runs it again.
  const [submitted, setSubmitted] = useState<{ query: string } | null>(() =>
    initialQuery.trim().length >= 3 ? { query: initialQuery.trim() } : null,
  );
  const [response, setResponse] = useState<SearchResponse | null>(null);
  // Kept as the error itself and described when shown, so it follows a language switch.
  const [error, setError] = useState<{ error: unknown } | null>(null);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);

  const requestKey = submitted ? submitted.query : null;

  useEffect(() => {
    if (!submitted || !requestKey) return;
    const controller = new AbortController();
    api
      .search({ query: submitted.query }, controller.signal)
      .then((result) => {
        setResponse(result);
        setError(null);
        setLoadingKey((current) => (current === requestKey ? null : current));
      })
      .catch((searchError) => {
        if (controller.signal.aborted) return;
        setError({ error: searchError });
        setLoadingKey((current) => (current === requestKey ? null : current));
      });
    return () => controller.abort();
  }, [submitted, requestKey]);

  const run = () => {
    const text = query.trim();
    if (text.length < 3) return;
    setLoadingKey(text);
    setSubmitted({ query: text });
    router.replace(`/arama?q=${encodeURIComponent(text)}`, { scroll: false });
  };

  const loading = loadingKey !== null || (submitted !== null && response === null && error === null);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[880px] flex-col gap-5 px-4 py-8 sm:px-6 lg:py-9">
        <div className="flex flex-col gap-1.5">
          <h1 className="m-0 text-[26px] font-semibold tracking-[-0.02em]">{t.heading}</h1>
          <p className="m-0 text-sm text-fg2">{t.lead}</p>
        </div>

        <form
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            run();
          }}
          className="flex h-[50px] items-center gap-2.5 rounded-xl border border-line-strong bg-surface pl-4 pr-1.5 shadow-soft transition-colors focus-within:border-fg3"
        >
          <Icon name="search" size={18} className="text-fg3" />
          <label htmlFor="kaynak-ara" className="sr-only">
            {t.label}
          </label>
          <input
            id="kaynak-ara"
            type="search"
            value={query}
            minLength={3}
            maxLength={500}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t.placeholder}
            className="min-w-0 grow border-0 bg-transparent text-[15px] text-fg outline-none placeholder:text-fg3"
          />
          <button
            type="submit"
            disabled={query.trim().length < 3}
            className="flex h-[38px] items-center gap-2 rounded-[9px] bg-inv px-4 text-[13.5px] font-medium text-inv-fg disabled:opacity-40"
          >
            {loading && <Spinner size={14} />}
            {t.submit}
          </button>
        </form>

        <p className="m-0 text-[12.5px] text-fg3">{t.tech}</p>

        {error && (
          <p role="alert" className="m-0 rounded-[10px] border border-err-line bg-err-bg px-3.5 py-2.5 text-[13px] text-err">
            {describeError(error.error, m)}
          </p>
        )}

        {!submitted && (
          <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-line-strong px-6 py-12 text-center">
            <Icon name="book" size={22} className="text-fg3" />
            <p className="m-0 text-sm font-medium">{t.emptyTitle}</p>
            <p className="m-0 max-w-md text-[13px] text-fg3">{t.emptyBody}</p>
          </div>
        )}

        {response && (
          <div className={`flex flex-col gap-4 transition-opacity ${loading ? 'opacity-50' : ''}`} aria-busy={loading}>
            <div className="flex items-center justify-between text-[13px] text-fg3">
              <span>
                <span className="font-semibold text-fg">{t.primary}</span> · {t.results(response.results.length)}
              </span>
              <span>{t.ranked}</span>
            </div>
            <div className="flex flex-col border-t border-line">
              {response.results.length === 0 && <p className="m-0 py-6 text-sm text-fg3">{t.noResults}</p>}
              {response.results.map((result) => (
                <ResultCard key={result.chunk_id} result={result} query={response.query} />
              ))}
            </div>
            {response.doctrine_results.length > 0 && (
              <>
                <div className="flex items-center gap-2 pt-2 text-[13px] text-fg3">
                  <span className="size-2 rounded-[2px] bg-doc" />
                  <span>
                    <span className="font-semibold text-fg">{t.doctrine}</span> · {t.results(response.doctrine_results.length)}
                  </span>
                </div>
                <div className="flex flex-col gap-3">
                  {response.doctrine_results.map((result) => (
                    <div key={result.chunk_id} className="rounded-xl border border-doc-line bg-surface px-[18px]">
                      <ResultCard result={result} query={response.query} />
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
