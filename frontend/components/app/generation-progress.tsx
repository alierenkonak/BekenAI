'use client';

import { LogoMark } from '@/components/brand';
import { Icon, Spinner } from '@/components/icons';
import { formatElapsed } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import type { GenerationSummary } from '@/lib/types';

const CORPUS_STEPS = [
  { title: 'Sırada', detail: 'İsteğiniz işlenmek üzere kuyruğa alındı' },
  { title: 'Kaynaklar aranıyor', detail: 'Mevzuat, Yargıtay kararları ve doktrin taranıyor' },
  { title: 'Cevap hazırlanıyor', detail: 'Yalnızca bulunan kaynaklarla taslak yazılıyor' },
  { title: 'İddialar doğrulanıyor', detail: 'Her iddia, dayandığı pasajla ayrıca karşılaştırılıyor' },
];

const ANALYSIS_STEPS = [
  CORPUS_STEPS[0],
  { title: 'Dosyalar okunuyor', detail: 'Bütün dosyalar okunup davanın hukuki konuları çıkarılıyor ve her biri için kanun aranıyor' },
  { title: 'Rapor yazılıyor', detail: 'Her konu için kanunun aradığı, dosyada olan ve değerlendirme yazılıyor' },
  { title: 'İddialar doğrulanıyor', detail: 'Her iddia, dayandığı kanun pasajı ya da dosya pasajıyla karşılaştırılıyor' },
];

// With web search on, the usual search runs and the web is searched alongside it.
const WEB_STEPS = [
  CORPUS_STEPS[0],
  { title: 'Kaynaklar ve web aranıyor', detail: 'Mevzuat, Yargıtay kararları ve web sayfaları taranıyor' },
  { title: 'Cevap hazırlanıyor', detail: 'Cevap kaynaklarla, en alttaki web bölümü bulunan sayfalarla yazılıyor' },
  { title: 'İddialar doğrulanıyor', detail: 'Her iddia, dayandığı pasajla ya da sayfa alıntısıyla karşılaştırılıyor' },
];

function currentStep(generation: GenerationSummary): number {
  if (generation.status === 'queued') return 0;
  if (generation.stage === 'generating') return 2;
  if (generation.stage === 'verifying') return 3;
  return 1;
}

export function GenerationProgress({
  generation,
  onCancel,
  cancelling,
}: {
  generation: GenerationSummary;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const now = useNow(1000);
  const steps = generation.search_mode === 'analysis' ? ANALYSIS_STEPS : generation.search_mode === 'web' ? WEB_STEPS : CORPUS_STEPS;
  const active = currentStep(generation);
  const elapsed = now ? formatElapsed(now - new Date(generation.created_at).getTime()) : null;

  return (
    <section aria-live="polite" aria-label="Cevap hazırlanıyor" className="flex flex-col gap-3.5">
      <div className="flex items-center gap-2">
        <LogoMark size={22} />
        <span className="text-[13.5px] font-semibold">BekenAI</span>
        <span className="text-[13px] text-fg2">{steps[active].title}</span>
      </div>
      <div className="flex flex-col rounded-[14px] border border-line bg-surface">
        <ol className="m-0 flex list-none flex-col px-5 pb-1.5 pt-[18px]">
          {steps.map((step, index) => {
            const done = index < active;
            const on = index === active;
            const last = index === steps.length - 1;
            return (
              <li key={step.title} className="flex gap-3.5">
                <div className="flex flex-col items-center">
                  {done ? (
                    <span className="flex size-5 items-center justify-center rounded-full bg-ok text-inv-fg">
                      <Icon name="check" size={12} strokeWidth={3} />
                    </span>
                  ) : on ? (
                    <Spinner size={20} className="text-accent" />
                  ) : (
                    <span className="size-5 rounded-full border-2 border-line-strong" />
                  )}
                  {!last && <span className={`min-h-3.5 w-0.5 grow ${done ? 'bg-ok/35' : 'bg-line'}`} />}
                </div>
                <div className="flex grow justify-between gap-3 pb-3.5">
                  <div className="flex flex-col gap-0.5">
                    <span className={`text-sm ${on ? 'font-semibold text-accent' : done ? 'font-medium' : 'font-medium text-fg3'}`}>
                      {step.title}
                    </span>
                    {(on || !done) && index > 0 && (
                      <span className={`text-[13px] ${on ? 'text-fg2' : 'text-fg3'}`}>{step.detail}</span>
                    )}
                  </div>
                  {on && elapsed && <span className="font-mono text-xs text-fg2">{elapsed}</span>}
                </div>
              </li>
            );
          })}
        </ol>
        <div className="flex flex-wrap items-center gap-4 border-t border-line px-5 py-3">
          <span className="min-w-[220px] grow text-[12.5px] leading-normal text-fg3">
            {generation.search_mode === 'analysis' ? 'Genellikle 2–4 dakika sürer.' : 'Genellikle 1–2 dakika sürer.'} Sayfadan
            ayrılabilirsiniz; cevap hazır olduğunda bu sohbette görünür.
          </span>
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelling}
            className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-line-strong bg-surface px-3 text-[13px] font-medium text-fg hover:bg-hover disabled:opacity-60"
          >
            {cancelling ? <Spinner size={14} /> : <Icon name="x" size={14} strokeWidth={1.9} />}
            İptal et
          </button>
        </div>
      </div>
      <div aria-hidden="true" className="flex animate-pulse flex-col gap-2.5 pt-1.5">
        <span className="h-3 w-[92%] rounded-md bg-muted" />
        <span className="h-3 w-[78%] rounded-md bg-muted" />
        <span className="h-3 w-[85%] rounded-md bg-muted" />
      </div>
    </section>
  );
}
