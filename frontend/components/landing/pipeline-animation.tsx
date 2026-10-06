'use client';

import { Fragment, useEffect, useRef, useState } from 'react';
import { Icon } from '@/components/icons';
import { useInView, useReducedMotion } from '@/lib/hooks';

const STEP = 60; // 100 ms ticks → 6 s per step
// The first three steps run once, as sources are added; the rest run for every question.
const PREPARATION_STEPS = 3;
const STEPS = [
  { title: 'Kaynakları toplar', en: 'Ingestion', caption: 'manifest → sha256 kontrolü → sürümlü depo' },
  { title: 'Metni parçalara ayırır', en: 'Chunking', caption: 'madde / fıkra / bent yapısı korunur' },
  { title: 'Dizine ekler', en: 'Embedding & indexing', caption: 'BGE-M3 → 1024 boyutlu vektör → Qdrant · BM25' },
  { title: 'İlgili pasajları bulur', en: 'Hybrid retrieval', caption: 'sorgu planlama → BM25 + BGE-M3 → RRF (k=60)' },
  { title: 'En alakalıları seçer', en: 'Reranking', caption: 'bge-reranker-v2-m3 · cross-encoder' },
  { title: 'Kaynaklara dayanarak yazar', en: 'Generation', caption: 'Gemini · JSON şemalı yapılandırılmış çıktı' },
  { title: 'Her iddiayı doğrular', en: 'Verification', caption: 'supported · partial · unsupported' },
];

type State = { t: number; paused: boolean };

export function PipelineAnimation() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref);
  const reduced = useReducedMotion();
  const [state, setState] = useState<State>({ t: 0, paused: false });

  useEffect(() => {
    if (!inView) return;
    const id = window.setInterval(() => {
      setState((current) => {
        if (current.paused || reduced) {
          // A paused scene finishes its own animation and then holds.
          const end = Math.floor(current.t / STEP) * STEP + STEP - 1;
          return current.t < end ? { ...current, t: current.t + 1 } : current;
        }
        return { ...current, t: (current.t + 1) % (STEPS.length * STEP) };
      });
    }, 100);
    return () => window.clearInterval(id);
  }, [inView, reduced]);

  const step = Math.floor(state.t / STEP);
  const L = state.t % STEP;
  const paused = state.paused || reduced;

  const selectStep = (index: number) => {
    setState((current) =>
      index === Math.floor(current.t / STEP) ? { ...current, paused: !current.paused } : { ...current, t: index * STEP },
    );
  };

  return (
    <div ref={ref} className="grid grid-cols-1 gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
      <ol aria-label="Cevap hattının adımları" className="m-0 grid list-none grid-cols-2 gap-2 p-0 sm:grid-cols-3 xl:flex xl:flex-col">
        {STEPS.map((item, index) => {
          const done = index < step;
          const on = index === step;
          return (
            <Fragment key={item.en}>
              {(index === 0 || index === PREPARATION_STEPS) && (
                <li aria-hidden="true" className="col-span-full flex items-center gap-2 pt-1 text-[11px] font-semibold tracking-[0.12em] text-fg3 first:pt-0">
                  {index === 0 ? 'HAZIRLIK · KAYNAKLAR EKLENİRKEN BİR KEZ' : 'HER SORUDA'}
                  <span className="h-px grow bg-line" />
                </li>
              )}
              <li className="flex">
                <button
                  type="button"
                  aria-current={on ? 'step' : undefined}
                  aria-label={
                    on
                      ? `${item.title}, ${paused ? 'duraklatıldı. Devam etmek için tıklayın.' : 'oynatılıyor. Duraklatmak için tıklayın.'}`
                      : `${item.title} adımına geç`
                  }
                  onClick={() => selectStep(index)}
                  className={`relative flex min-h-[64px] grow items-center gap-3 overflow-hidden rounded-[14px] border px-3 text-left transition-colors xl:h-[76px] xl:px-4 ${
                    on ? 'border-accent-line bg-surface' : 'border-line bg-transparent hover:bg-surface'
                  }`}
                >
                  <span
                    className={`flex size-[30px] shrink-0 items-center justify-center rounded-[9px] border font-mono text-[12.5px] font-medium transition-colors ${
                      done ? 'border-ok bg-ok text-inv-fg' : on ? 'border-accent bg-accent-bg text-accent' : 'border-line-strong text-fg3'
                    }`}
                  >
                    {done ? '✓' : index + 1}
                  </span>
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className={`text-sm font-semibold xl:text-[15px] ${on || done ? 'text-fg' : 'text-fg2'}`}>{item.title}</span>
                    <span className="font-mono text-[11.5px] text-fg3">{item.en}</span>
                  </span>
                  {on && paused && !reduced && (
                    <span className="ml-auto hidden h-[22px] shrink-0 items-center gap-1 rounded-full bg-muted px-2 text-[11px] font-medium text-fg2 sm:flex">
                      <svg width="9" height="9" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
                        <path d="M6 4h4v16H6zM14 4h4v16h-4z" />
                      </svg>
                      Duraklatıldı
                    </span>
                  )}
                  <span
                    className="absolute bottom-0 left-0 h-0.5 bg-accent transition-[width] duration-100 ease-linear"
                    style={{ width: on && !paused ? `${Math.round(((L + 1) / STEP) * 100)}%` : 0 }}
                  />
                </button>
              </li>
            </Fragment>
          );
        })}
      </ol>

      <div
        role="img"
        aria-label={`Adım ${step + 1}: ${STEPS[step].title}`}
        className="flex min-h-[460px] flex-col gap-[18px] overflow-hidden rounded-[18px] border border-line bg-surface px-5 py-6 sm:px-7"
      >
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line pb-3.5">
          <span className="font-mono text-xs text-accent">
            Adım {step + 1} / {STEPS.length} · {step < PREPARATION_STEPS ? 'hazırlık' : 'her soruda'}
          </span>
          <span className="grow text-[17px] font-semibold">{STEPS[step].title}</span>
          <span className="font-mono text-[11.5px] text-fg3">{STEPS[step].caption}</span>
        </div>
        {step === 0 && <IngestScene L={L} />}
        {step === 1 && <ChunkScene L={L} />}
        {step === 2 && <IndexScene L={L} />}
        {step === 3 && <SearchScene L={L} />}
        {step === 4 && <RerankScene L={L} />}
        {step === 5 && <WriteScene L={L} />}
        {step === 6 && <VerifyScene L={L} />}
      </div>
    </div>
  );
}

function fade(on: boolean, dy = 6) {
  return { opacity: on ? 1 : 0, transform: `translateY(${on ? 0 : dy}px)` };
}

function IngestScene({ L }: { L: number }) {
  const docs = [
    { pill: 'Mevzuat', cls: 'bg-accent-bg text-accent', title: '4857 sayılı İş Kanunu', meta: 'kanun · 122 madde' },
    { pill: 'İçtihat', cls: 'bg-muted text-fg2', title: 'Yargıtay 9. Hukuk Dairesi', meta: 'karar · iş hukuku' },
    { pill: 'Doktrin', cls: 'bg-doc-bg text-doc', title: 'İş Hukuku Ders Notu (2026)', meta: 'ders notu · izinli kaynak' },
  ];
  const stored = [10, 13, 16].filter((value) => L >= value).length;
  return (
    <div className="grid grow grid-cols-1 items-center gap-4 md:grid-cols-[minmax(0,1fr)_48px_280px] md:gap-0">
      <div className="flex flex-col gap-2.5">
        {docs.map((doc, index) => (
          <div
            key={doc.title}
            className="flex min-h-[72px] items-center gap-3.5 rounded-xl border border-line bg-bg px-4 transition-all duration-500"
            style={{ opacity: L >= 1 + index * 3 ? 1 : 0, transform: `translateX(${L >= 1 + index * 3 ? 0 : -14}px)` }}
          >
            <span className={`flex h-[22px] shrink-0 items-center rounded-md px-2 text-[11.5px] font-medium ${doc.cls}`}>{doc.pill}</span>
            <span className="flex min-w-0 grow flex-col gap-0.5">
              <span className="text-sm font-semibold">{doc.title}</span>
              <span className="text-xs text-fg3">{doc.meta}</span>
            </span>
            <span className="font-mono text-[11px] text-ok transition-opacity" style={{ opacity: L >= 6 + index * 3 ? 1 : 0 }}>
              sha256 ✓
            </span>
          </div>
        ))}
      </div>
      <div aria-hidden="true" className="hidden justify-center text-fg3 md:flex">
        <Icon name="arrowRight" size={22} strokeWidth={1.6} />
      </div>
      <div className="flex flex-col gap-3 rounded-[14px] border border-accent-line bg-bg p-5">
        <span className="text-xs font-semibold tracking-[0.12em] text-fg3">SÜRÜMLÜ KAYNAK DEPOSU</span>
        <span className="font-mono text-[13px] text-accent">labour-law-pilot-v4</span>
        <span className="font-serif text-5xl leading-none">
          {stored} <span className="font-sans text-sm text-fg2">/ 3 belge</span>
        </span>
        <span className="text-[12.5px] text-ok transition-opacity" style={{ opacity: L >= 19 ? 1 : 0 }}>
          ✓ Ham kopya değiştirilemez olarak saklandı
        </span>
      </div>
    </div>
  );
}

function ChunkScene({ L }: { L: number }) {
  const chunks = [
    ['Belirsiz süreli iş sözleşmelerinin feshinden önce durumun diğer tarafa bildirilmesi gerekir.', 'md. 17/1'],
    ['d) İşi üç yıldan fazla sürmüş işçi için, bildirimin diğer tarafa yapılmasından başlayarak sekiz hafta sonra feshedilmiş sayılır.', 'md. 17/2-d'],
    ['Bu süreler asgari olup sözleşmeler ile artırılabilir.', 'md. 17/3'],
    ['Bildirim şartına uymayan taraf, bildirim süresine ilişkin ücret tutarında tazminat ödemek zorundadır.', 'md. 17/4'],
  ];
  const split = L >= 6;
  return (
    <div className="flex grow flex-col gap-3">
      <span className="text-[13px] text-fg2">
        <span className="font-semibold text-fg">4857 sayılı İş Kanunu</span> · Madde 17 · Süreli fesih
      </span>
      <div className="flex flex-col transition-[gap] duration-500" style={{ gap: split ? 10 : 0 }}>
        {chunks.map(([text, label], index) => (
          <div
            key={label}
            className="flex items-center gap-4 border bg-bg px-3.5 py-2.5 transition-all duration-500"
            style={{ borderColor: split ? 'var(--line)' : 'transparent', borderRadius: split ? 10 : 0 }}
          >
            <span className="grow text-[13.5px] leading-normal text-fg2">{text}</span>
            <span
              className="flex h-[22px] shrink-0 items-center rounded-md bg-accent-bg px-2 font-mono text-[11px] text-accent transition-opacity"
              style={{ opacity: L >= 10 + index * 3 ? 1 : 0 }}
            >
              {label}
            </span>
          </div>
        ))}
      </div>
      <span className="font-mono text-[11.5px] text-fg3 transition-opacity" style={{ opacity: L >= 22 ? 1 : 0 }}>
        4 parça · her biri künye, madde yolu ve sayfa bilgisini taşır
      </span>
    </div>
  );
}

const INDEXED = [
  { label: 'md. 17/1', vector: ['0.021', '−0.137', '0.058'], bars: [5, 9, 3, 7, 11, 4, 8, 6, 10, 2, 7, 5] },
  { label: 'md. 17/2-d', vector: ['−0.044', '0.102', '0.019'], bars: [8, 4, 10, 6, 3, 9, 5, 11, 4, 7, 2, 8] },
  { label: 'md. 17/4', vector: ['0.073', '−0.015', '0.126'], bars: [3, 7, 5, 11, 8, 2, 10, 4, 6, 9, 5, 7] },
];
// "Bildirim şartına uymayan taraf, bildirim süresine ilişkin ücret tutarında tazminat ödemek
// zorundadır." cut to the first five letters of each word, as the legislation index stores it.
const TOKENS = ['bildi', 'şartı', 'uymay', 'taraf', 'süres', 'ilişk', 'ücret', 'tutar', 'tazmi', 'ödeme', 'zorun'];

function IndexScene({ L }: { L: number }) {
  return (
    <div className="grid grow grid-cols-1 items-center gap-4 md:grid-cols-[236px_40px_minmax(0,1fr)] md:gap-0">
      <div className="flex flex-col gap-2.5">
        <span className="text-xs font-semibold text-fg2">Parçalar</span>
        {INDEXED.map((chunk, index) => (
          <div
            key={chunk.label}
            className="flex h-11 items-center gap-2.5 rounded-[10px] border border-line bg-bg px-3 text-[12.5px] transition-all duration-500"
            style={fade(L >= 1 + index * 2)}
          >
            <span className="flex h-[22px] shrink-0 items-center whitespace-nowrap rounded-md bg-accent-bg px-2 font-mono text-[11px] text-accent">{chunk.label}</span>
            <span className="truncate text-fg3">4857 · Madde 17</span>
          </div>
        ))}
      </div>
      <div aria-hidden="true" className="hidden justify-center text-fg3 md:flex">
        <Icon name="arrowRight" size={20} strokeWidth={1.6} />
      </div>
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-2 rounded-[14px] border border-accent-line bg-bg p-4">
          <span className="flex items-center gap-2 text-xs font-semibold text-fg2">
            Vektör dizini · Qdrant
            <span className="ml-auto font-mono text-[11px] font-normal text-fg3">BGE-M3 · 1024 boyut</span>
          </span>
          {INDEXED.map((chunk, index) => (
            <div key={chunk.label} className="flex items-center gap-3 transition-all duration-500" style={fade(L >= 8 + index * 3)}>
              <span className="w-[74px] shrink-0 font-mono text-[11px] text-accent">{chunk.label}</span>
              <span aria-hidden="true" className="flex h-4 items-end gap-[2px]">
                {chunk.bars.map((height, bar) => (
                  <span key={bar} className="w-[3px] rounded-sm bg-accent/70" style={{ height }} />
                ))}
              </span>
              <span className="truncate font-mono text-[11px] text-fg2">[{chunk.vector.join(', ')}, …]</span>
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-2 rounded-[14px] border border-line bg-bg p-4">
          <span className="flex items-center gap-2 text-xs font-semibold text-fg2">
            Kelime dizini · BM25
            <span className="ml-auto font-mono text-[11px] font-normal text-fg3">md. 17/4 · ilk 5 harf</span>
          </span>
          <div className="flex flex-wrap gap-1.5">
            {TOKENS.map((token, index) => (
              <span
                key={token}
                className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-fg2 transition-opacity duration-300"
                style={{ opacity: L >= 18 + index ? 1 : 0 }}
              >
                {token}
              </span>
            ))}
          </div>
        </div>
        <span className="font-mono text-[11.5px] text-fg3 transition-opacity" style={{ opacity: L >= 32 ? 1 : 0 }}>
          Soru geldiğinde aynı model soruyu da vektöre çevirir; arama bu iki dizinde yapılır.
        </span>
      </div>
    </div>
  );
}

function SearchScene({ L }: { L: number }) {
  const columns = [
    { title: 'Anahtar kelime · BM25', items: [['1', 'İş K. md. 17/4 · tazminat', 3], ['2', 'İş K. md. 17/2 · bildirim süreleri', 5], ['3', 'Yargıtay · ihbar tazminatı', 7]] },
    { title: 'Anlam · BGE-M3', items: [['1', 'Yargıtay · ihbar tazminatı', 4], ['2', 'İş K. md. 17/4 · tazminat', 6], ['3', 'İş K. md. 25 · haklı fesih', 8]] },
  ] as const;
  const fused = [
    ['1', 'İş K. md. 17/4 · tazminat', '0.0325'],
    ['2', 'Yargıtay · ihbar tazminatı', '0.0323'],
    ['3', 'İş K. md. 17/2 · bildirim süreleri', '0.0161'],
    ['4', 'İş K. md. 25 · haklı fesih', '0.0159'],
  ];
  return (
    <div className="flex grow flex-col gap-4">
      <div className="flex h-10 items-center gap-2.5 rounded-[10px] border border-line-strong bg-bg px-3.5 text-sm">
        <Icon name="search" size={15} className="text-fg3" />
        Bildirim süresi verilmeden çıkarıldım, ne alabilirim?
      </div>
      <div className="grid grid-cols-1 items-start gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_28px_minmax(0,1.1fr)]">
        {columns.map((column) => (
          <div key={column.title} className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-fg2">{column.title}</span>
            {column.items.map(([rank, label, at]) => (
              <div
                key={label}
                className="flex h-10 items-center gap-2.5 rounded-[9px] border border-line bg-bg px-3 text-[12.5px] transition-all duration-300"
                style={fade(L >= at)}
              >
                <span className="font-mono text-[11px] text-fg3">{rank}</span>
                <span className="truncate">{label}</span>
              </div>
            ))}
          </div>
        ))}
        <div aria-hidden="true" className="hidden justify-center pt-[74px] text-fg3 md:flex">
          <Icon name="arrowRight" size={20} strokeWidth={1.6} />
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-xs font-semibold text-accent">Birleşik sıra · RRF</span>
          {fused.map(([rank, label, score], index) => (
            <div
              key={label}
              className="flex h-10 items-center gap-2.5 rounded-[9px] border border-accent-line bg-accent-bg px-3 text-[12.5px] transition-all duration-300"
              style={fade(L >= 13 + index * 2)}
            >
              <span className="font-mono text-[11px] text-accent">{rank}</span>
              <span className="grow truncate">{label}</span>
              <span className="font-mono text-[11px] text-fg2">{score}</span>
            </div>
          ))}
        </div>
      </div>
      <span className="font-mono text-[11.5px] text-fg3 transition-opacity" style={{ opacity: L >= 12 ? 1 : 0 }}>
        RRF skoru = Σ 1 / (60 + sıra) · iki listede de üst sıralarda olan pasaj öne çıkar
      </span>
    </div>
  );
}

function RerankScene({ L }: { L: number }) {
  const after = L >= 10;
  const rows: [string, number, number, number, number][] = [
    ['İş K. md. 17/4 · tazminat', 0, 0, 0.0325, 0.94],
    ['Yargıtay · ihbar tazminatı', 1, 1, 0.0323, 0.89],
    ['İş K. md. 25 · haklı fesih', 2, 4, 0.0161, 0.21],
    ['İş K. md. 18 · geçerli fesih', 3, 3, 0.0159, 0.47],
    ['İş K. md. 17/2 · bildirim süreleri', 4, 2, 0.0156, 0.82],
  ];
  return (
    <div className="flex grow flex-col gap-3.5">
      <div className="flex items-center gap-3 text-xs text-fg3">
        <span className="font-semibold text-fg2">25 adaydan ilk 5</span>
        <span className="ml-auto font-mono text-[11px]">{after ? 'cross-encoder skoru' : 'RRF skoru'}</span>
      </div>
      <div className="relative h-[290px]">
        {rows.map(([label, rrfRank, rerankRank, rrfScore, rerankScore]) => {
          const position = after ? rerankRank : rrfRank;
          const picked = after && L >= 18 && rerankRank < 3;
          const dropped = after && L >= 18 && rerankRank >= 3;
          return (
            <div
              key={label}
              className="absolute inset-x-0 flex h-[50px] items-center gap-3.5 rounded-[10px] border bg-bg px-3.5 transition-all duration-700"
              style={{
                top: position * 58,
                opacity: dropped ? 0.45 : 1,
                borderColor: picked ? 'var(--accent-line)' : 'var(--line)',
              }}
            >
              <span className="w-[42%] shrink-0 truncate text-[13px] sm:w-60">{label}</span>
              <span className="h-1.5 grow overflow-hidden rounded-full bg-muted">
                <span
                  className="block h-full rounded-full transition-all duration-700"
                  style={{
                    width: `${after ? Math.round(rerankScore * 100) : Math.round((rrfScore / 0.0325) * 60)}%`,
                    background: after ? 'var(--accent)' : 'var(--fg3)',
                  }}
                />
              </span>
              <span className="w-[52px] shrink-0 text-right font-mono text-[11.5px] text-fg2">
                {after ? rerankScore.toFixed(2) : rrfScore.toFixed(4)}
              </span>
              <span
                className="hidden h-[22px] w-24 shrink-0 items-center justify-center rounded-full bg-ok-bg text-[11px] font-medium text-ok transition-opacity sm:flex"
                style={{ opacity: picked ? 1 : 0 }}
              >
                Bağlama alındı
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const WRITTEN = [
  { text: 'İşi üç yıldan fazla sürmüş işçi için bildirim süresi sekiz haftadır.', chips: ['3'] },
  { text: 'Bildirim şartına uymayan işveren, ihbar tazminatı ödemekle yükümlüdür.', chips: ['1', '2'] },
];
const WRITTEN_STARTS = WRITTEN.map((_, index) =>
  WRITTEN.slice(0, index).reduce((sum, line) => sum + line.text.length, 0),
);

function WriteScene({ L }: { L: number }) {
  const typed = Math.max(0, (L - 2) * 9);
  return (
    <div className="grid grow grid-cols-1 gap-6 md:grid-cols-[250px_minmax(0,1fr)]">
      <div className="flex flex-col gap-2.5">
        <span className="text-xs font-semibold text-fg2">Modele verilen bağlam</span>
        {[
          ['1', 'İş K. md. 17/4 · tazminat'],
          ['2', 'Yargıtay · ihbar tazminatı'],
          ['3', 'İş K. md. 17/2 · bildirim süreleri'],
        ].map(([n, label]) => (
          <div key={n} className="flex items-center gap-2 rounded-[9px] border border-line bg-bg px-2.5 py-2 text-[12.5px]">
            <span className="flex size-[18px] items-center justify-center rounded-[5px] bg-accent-bg font-mono text-[10.5px] text-accent">{n}</span>
            {label}
          </div>
        ))}
        <span className="pt-1.5 text-[11.5px] text-fg3">Bağlam bütçesi · hedef 96k token</span>
        <span className="h-1.5 overflow-hidden rounded-full bg-muted">
          <span className="block h-full rounded-full bg-accent transition-all duration-700" style={{ width: L >= 1 ? '22%' : 0 }} />
        </span>
      </div>
      <div className="flex flex-col gap-3.5">
        {WRITTEN.map((line, index) => {
          const count = Math.max(0, Math.min(line.text.length, typed - WRITTEN_STARTS[index]));
          const complete = count >= line.text.length;
          return (
            <p key={line.text} className="m-0 text-[15px] leading-relaxed">
              {line.text.slice(0, count)}
              {count > 0 && !complete && <span className="ml-0.5 inline-block h-4 w-[7px] bg-accent align-[-2px]" />}
              {complete &&
                line.chips.map((chip) => (
                  <span
                    key={chip}
                    className="ml-1 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] border border-accent-line bg-accent-bg px-1 align-[1px] font-mono text-[10.5px] font-medium text-accent"
                  >
                    {chip}
                  </span>
                ))}
            </p>
          );
        })}
        <pre
          className="m-0 mt-auto whitespace-pre-wrap rounded-[10px] border border-line bg-bg px-3.5 py-3 font-mono text-[11.5px] leading-relaxed text-fg2 transition-opacity"
          style={{ opacity: L >= 20 ? 1 : 0 }}
        >
          {'{ "claim_id": "c2",\n  "source_ids": ["SOURCE_PRIMARY_01", "SOURCE_PRIMARY_02"] }'}
        </pre>
      </div>
    </div>
  );
}

function VerifyScene({ L }: { L: number }) {
  const checks = [
    ['İşi üç yıldan fazla sürmüş işçi için bildirim süresi sekiz haftadır.', '[3]', 'ok'],
    ['Bildirim şartına uymayan işveren, ihbar tazminatı ödemekle yükümlüdür.', '[1]', 'ok'],
    ['Bildirim şartına uymayan işveren, ihbar tazminatı ödemekle yükümlüdür.', '[2]', 'partial'],
    ['İşveren ayrıca kötüniyet tazminatı da ödemek zorundadır.', '[2]', 'no'],
  ] as const;
  return (
    <div className="flex grow flex-col gap-2.5">
      {checks.map(([claim, source, verdict], index) => {
        const shown = L >= 4 + index * 4;
        // As in the app: the unsupported citation is dropped and the sentence is marked, not deleted.
        const flagged = verdict === 'no' && L >= 24;
        return (
          <div
            key={`${claim}-${source}`}
            className="flex items-center gap-3.5 rounded-[10px] border border-line bg-bg px-3.5 py-3"
          >
            <span
              className={`grow text-[13.5px] leading-normal text-fg ${flagged ? 'underline decoration-err/70 decoration-dashed decoration-1 underline-offset-[5px]' : ''}`}
            >
              {claim}
            </span>
            <span className="hidden shrink-0 font-mono text-[11px] text-fg3 sm:inline">↔ {source}</span>
            <span
              className={`flex h-6 shrink-0 items-center rounded-full border px-2.5 text-[11.5px] font-medium transition-opacity ${
                verdict === 'ok'
                  ? 'border-transparent bg-ok-bg text-ok'
                  : verdict === 'partial'
                    ? 'border-dashed border-accent text-accent'
                    : 'border-transparent bg-err-bg text-err'
              }`}
              style={{ opacity: shown ? 1 : 0 }}
            >
              {verdict === 'ok' ? '✓ Destekliyor' : verdict === 'partial' ? '◐ Kısmen' : '✕ Desteklemiyor'}
            </span>
          </div>
        );
      })}
      <div className="flex flex-wrap items-center gap-2.5 pt-2 text-[13px] text-fg2 transition-opacity duration-500" style={{ opacity: L >= 22 ? 1 : 0 }}>
        <span className="flex h-6 items-center rounded-full bg-ok-bg px-2.5 text-xs font-medium text-ok">Doğrulandı</span>
        3 atıf doğrulandı. Desteklenmeyen atıf kaldırıldı ve dayanağı kalmayan 1 iddia “doğrulanamadı” diye işaretlendi; kullanıcı ona güvenmemesi gerektiğini cevapta görür.
      </div>
    </div>
  );
}
