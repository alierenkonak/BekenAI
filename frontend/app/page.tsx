'use client';

import { useEffect, useState } from 'react';

type ServiceState = 'checking' | 'ready' | 'unavailable';

type ReadyPayload = {
  status: 'ready' | 'not_ready';
  corpus_documents: number;
  dependencies: {
    postgres: { status: string };
    qdrant: { status: string };
  };
};

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export default function Home() {
  const [apiState, setApiState] = useState<ServiceState>('checking');
  const [ready, setReady] = useState<ReadyPayload | null>(null);

  useEffect(() => {
    let active = true;

    async function checkHealth() {
      try {
        const liveResponse = await fetch(`${apiUrl}/health/live`);
        if (!liveResponse.ok) throw new Error('API is not live');
        if (active) setApiState('ready');

        const readyResponse = await fetch(`${apiUrl}/health/ready`);
        const payload = (await readyResponse.json()) as ReadyPayload;
        if (active) setReady(payload);
      } catch {
        if (active) setApiState('unavailable');
      }
    }

    void checkHealth();
    return () => { active = false; };
  }, []);

  const serviceStatus = (name: 'postgres' | 'qdrant') =>
    ready?.dependencies[name].status === 'ready' ? 'ready' : 'waiting';

  return (
    <main className="min-h-screen bg-[#f3f6f4] text-[#17201e]">
      <header className="border-b border-[#dbe3df] bg-white/90 px-6 py-5 backdrop-blur sm:px-10">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-[#123d32] font-serif text-xl text-white">B</span>
            <div>
              <p className="text-lg font-bold tracking-[-0.04em]">Beken<span className="text-[#137455]">.ai</span></p>
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#75817d]">Türk İş Hukuku</p>
            </div>
          </div>
          <span className="rounded-full border border-[#cfe1da] bg-[#edf7f3] px-3 py-1.5 text-xs font-semibold text-[#126248]">Aşama 0</span>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl gap-10 px-6 py-14 sm:px-10 lg:grid-cols-[1.2fr_0.8fr] lg:py-24">
        <div className="self-center">
          <p className="mb-5 text-xs font-bold uppercase tracking-[0.16em] text-[#137455]">Kaynağa dayalı legal intelligence</p>
          <h1 className="max-w-3xl font-serif text-4xl leading-[1.08] tracking-[-0.035em] sm:text-6xl">
            Türk İş Hukuku araştırması için güvenilir bir temel.
          </h1>
          <p className="mt-7 max-w-2xl text-base leading-7 text-[#5f6c68] sm:text-lg">
            Beken.ai; mevzuat, içtihat ve özel dosyaları doğrulanabilir kaynak pasajlarıyla buluşturacak. Bu ilk sürüm proje altyapısının sağlıklı çalıştığını gösterir.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <a className="rounded-lg bg-[#126248] px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-[#0c4d38]" href={`${apiUrl}/docs`}>
              API belgelerini aç
            </a>
            <span className="rounded-lg border border-[#d3ddd9] bg-white px-5 py-3 text-sm font-medium text-[#52605c]">Corpus: {ready?.corpus_documents ?? 0} belge</span>
          </div>
        </div>

        <aside className="rounded-2xl border border-[#d9e2de] bg-white p-6 shadow-[0_18px_50px_rgba(18,61,50,0.08)] sm:p-8" aria-live="polite">
          <div className="mb-7 flex items-start justify-between gap-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-[#7b8783]">Sistem durumu</p>
              <h2 className="mt-2 font-serif text-2xl">Proje temeli</h2>
            </div>
            <StatusDot state={apiState} />
          </div>

          <div className="space-y-3">
            <ServiceRow label="Frontend" detail="Next.js · TypeScript" state="ready" />
            <ServiceRow label="Backend API" detail="FastAPI · Python" state={apiState === 'ready' ? 'ready' : 'waiting'} />
            <ServiceRow label="PostgreSQL" detail="Metadata katmanı" state={serviceStatus('postgres')} />
            <ServiceRow label="Qdrant" detail="Semantic index" state={serviceStatus('qdrant')} />
          </div>

          <div className="mt-7 rounded-xl border border-[#dce8e3] bg-[#f2f8f5] p-4 text-sm leading-6 text-[#426055]">
            <strong className="block text-[#164f3c]">Aşama 0 sınırı</strong>
            Retrieval, RAG ve veri ingestion özellikleri Aşama 1 ve sonrasında etkinleştirilecek.
          </div>
        </aside>
      </section>
    </main>
  );
}

function StatusDot({ state }: { state: ServiceState }) {
  const classes = state === 'ready' ? 'bg-emerald-500' : state === 'checking' ? 'bg-amber-400 animate-pulse' : 'bg-slate-300';
  return <span className={`mt-1 size-3 rounded-full ${classes}`} title={state} />;
}

function ServiceRow({ label, detail, state }: { label: string; detail: string; state: 'ready' | 'waiting' }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-[#e1e7e4] px-4 py-3.5">
      <div><p className="text-sm font-semibold">{label}</p><p className="mt-0.5 text-xs text-[#7a8682]">{detail}</p></div>
      <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.08em] ${state === 'ready' ? 'bg-[#e6f5ee] text-[#126248]' : 'bg-[#f1f3f2] text-[#7a8581]'}`}>
        {state === 'ready' ? 'Hazır' : 'Bekliyor'}
      </span>
    </div>
  );
}
