'use client';

import { FormEvent, useEffect, useState } from 'react';

type ServiceState = 'checking' | 'ready' | 'unavailable';
type ReadyPayload = {
  status: 'ready' | 'not_ready';
  corpus_documents: number;
  dependencies: {
    postgres: { status: string };
    qdrant: { status: string };
  };
};
type SearchResult = {
  chunk_id: string;
  domain: string;
  rank: number;
  score: number;
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
};
type SearchPayload = { results: SearchResult[] };

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export default function Home() {
  const [apiState, setApiState] = useState<ServiceState>('checking');
  const [ready, setReady] = useState<ReadyPayload | null>(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchMessage, setSearchMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function checkHealth() {
      try {
        const [liveResponse, readyResponse] = await Promise.all([
          fetch(`${apiUrl}/health/live`),
          fetch(`${apiUrl}/health/ready`),
        ]);
        if (!liveResponse.ok) throw new Error('API is not live');
        const payload = (await readyResponse.json()) as ReadyPayload;
        if (active) {
          setApiState('ready');
          setReady(payload);
        }
      } catch {
        if (active) setApiState('unavailable');
      }
    }
    void checkHealth();
    return () => { active = false; };
  }, []);

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = query.trim();
    if (normalized.length < 3) {
      setSearchMessage('En az 3 karakterlik bir soru yazın.');
      return;
    }
    setSearching(true);
    setSearchMessage(null);
    try {
      const response = await fetch(`${apiUrl}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: normalized,
          domains: ['labour_law'],
          mode: 'hybrid_rerank',
          limit: 10,
          filters: { domain_roles: ['core', 'supplemental'] },
        }),
      });
      if (response.status === 503) {
        setResults([]);
        setSearchMessage('İş hukuku arama indeksi hazırlanıyor. BM25, vektör ve reranker kalite kapıları tamamlanınca arama açılacak.');
        return;
      }
      if (!response.ok) throw new Error('Search failed');
      const payload = (await response.json()) as SearchPayload;
      setResults(payload.results);
      setSearchMessage(payload.results.length ? null : 'Bu sorgu için eşleşen kaynak pasajı bulunamadı.');
    } catch {
      setResults([]);
      setSearchMessage('Arama servisine şu anda ulaşılamıyor.');
    } finally {
      setSearching(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f3f6f4] text-[#17201e]">
      <header className="border-b border-[#dbe3df] bg-white/90 px-6 py-5 backdrop-blur sm:px-10">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-[#123d32] font-serif text-xl text-white">B</span>
            <div>
              <p className="text-lg font-bold tracking-[-0.04em]">Beken<span className="text-[#137455]">.ai</span></p>
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#75817d]">Türk Hukuku Araştırması</p>
            </div>
          </div>
          <span className="rounded-full border border-[#cfe1da] bg-[#edf7f3] px-3 py-1.5 text-xs font-semibold text-[#126248]">Aşama 2</span>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 py-12 sm:px-10 lg:py-16">
        <div className="max-w-3xl">
          <p className="mb-4 text-xs font-bold uppercase tracking-[0.16em] text-[#137455]">Domain-aware hybrid retrieval</p>
          <h1 className="font-serif text-4xl leading-[1.08] tracking-[-0.035em] sm:text-6xl">Hukuki kaynağın içindeki doğru pasajı bulun.</h1>
          <p className="mt-6 text-base leading-7 text-[#5f6c68] sm:text-lg">İlk destek alanı Türk İş Hukuku. Diğer hukuk alanları aynı altyapıya bağımsız corpus, indeks ve kalite kapılarıyla eklenecek.</p>
        </div>

        <form onSubmit={submitSearch} className="mt-9 rounded-2xl border border-[#d9e2de] bg-white p-4 shadow-[0_18px_50px_rgba(18,61,50,0.08)] sm:p-5">
          <div className="grid gap-3 sm:grid-cols-[190px_1fr_auto]">
            <label className="sr-only" htmlFor="domain">Hukuk alanı</label>
            <select id="domain" className="rounded-xl border border-[#d8e1dd] bg-[#f8faf9] px-4 py-3 text-sm font-semibold outline-none focus:border-[#137455]" defaultValue="labour_law">
              <option value="labour_law">İş Hukuku</option>
              <option disabled>Vergi Hukuku · hazırlanıyor</option>
              <option disabled>Ceza Hukuku · hazırlanıyor</option>
              <option disabled>Ticaret Hukuku · hazırlanıyor</option>
              <option disabled>İdare Hukuku · hazırlanıyor</option>
            </select>
            <label className="sr-only" htmlFor="legal-query">Hukuki soru</label>
            <input id="legal-query" value={query} onChange={(event) => setQuery(event.target.value)} className="min-w-0 rounded-xl border border-[#d8e1dd] px-4 py-3 text-sm outline-none placeholder:text-[#8a9692] focus:border-[#137455]" placeholder="Örn. Fazla çalışma alacağında ispat yükü kimdedir?" maxLength={500} />
            <button type="submit" disabled={searching} className="rounded-xl bg-[#126248] px-6 py-3 text-sm font-semibold text-white transition hover:bg-[#0c4d38] disabled:cursor-wait disabled:opacity-60">{searching ? 'Aranıyor…' : 'Kaynak ara'}</button>
          </div>
          {searchMessage && <p className="mt-4 rounded-xl bg-[#f5f8f6] px-4 py-3 text-sm leading-6 text-[#52605c]" role="status">{searchMessage}</p>}
        </form>

        <div className="mt-8 grid gap-7 lg:grid-cols-[1fr_290px]">
          <section className="space-y-4" aria-label="Arama sonuçları">
            {results.map((result) => <ResultCard key={result.chunk_id} result={result} />)}
          </section>
          <aside className="h-fit rounded-2xl border border-[#d9e2de] bg-white p-5" aria-live="polite">
            <div className="flex items-center justify-between"><h2 className="font-serif text-xl">Sistem durumu</h2><StatusDot state={apiState} /></div>
            <dl className="mt-5 space-y-3 text-sm">
              <StatusRow label="API" ready={apiState === 'ready'} />
              <StatusRow label="PostgreSQL" ready={ready?.dependencies.postgres.status === 'ready'} />
              <StatusRow label="Qdrant" ready={ready?.dependencies.qdrant.status === 'ready'} />
              <div className="flex justify-between gap-4 border-t border-[#e4e9e7] pt-3"><dt className="text-[#697570]">Corpus</dt><dd className="font-semibold">{ready?.corpus_documents ?? 0} belge</dd></div>
            </dl>
            <a className="mt-5 block rounded-lg border border-[#d3ddd9] px-4 py-2.5 text-center text-xs font-semibold text-[#52605c] hover:bg-[#f6f8f7]" href={`${apiUrl}/docs`}>API belgeleri</a>
          </aside>
        </div>
      </section>
    </main>
  );
}

function ResultCard({ result }: { result: SearchResult }) {
  const references = [result.case_number && `E. ${result.case_number}`, result.decision_number && `K. ${result.decision_number}`].filter(Boolean).join(' · ');
  return (
    <article className="rounded-2xl border border-[#d9e2de] bg-white p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4"><div><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#137455]">#{result.rank} · {result.document_type}</p><h2 className="mt-2 font-serif text-xl leading-7">{result.title}</h2></div><span className="rounded-full bg-[#edf7f3] px-2.5 py-1 text-[10px] font-bold text-[#126248]">{result.score.toFixed(4)}</span></div>
      {(references || result.document_date) && <p className="mt-2 text-xs text-[#75817d]">{references}{references && result.document_date ? ' · ' : ''}{result.document_date}</p>}
      {result.breadcrumb.length > 0 && <p className="mt-4 text-xs font-medium text-[#6c7874]">{result.breadcrumb.join(' › ')}</p>}
      <p className="mt-3 whitespace-pre-wrap rounded-xl bg-[#f6f8f7] p-4 text-sm leading-6 text-[#34423e]">{result.exact_passage}</p>
      <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-[#6c7874]"><span>{result.page_number ? `Sayfa ${result.page_number}` : result.section_type}</span><span>Corpus: {result.corpus_version}</span>{result.source_url && <a className="font-semibold text-[#126248] underline decoration-[#a8c9bd] underline-offset-4" href={result.source_url} target="_blank" rel="noreferrer">Resmî kaynağı aç</a>}</div>
    </article>
  );
}

function StatusDot({ state }: { state: ServiceState }) {
  const classes = state === 'ready' ? 'bg-emerald-500' : state === 'checking' ? 'animate-pulse bg-amber-400' : 'bg-slate-300';
  return <span className={`size-3 rounded-full ${classes}`} title={state} />;
}

function StatusRow({ label, ready }: { label: string; ready: boolean }) {
  return <div className="flex justify-between gap-4"><dt className="text-[#697570]">{label}</dt><dd className={ready ? 'font-semibold text-[#126248]' : 'font-semibold text-[#8a9692]'}>{ready ? 'Hazır' : 'Bekliyor'}</dd></div>;
}
