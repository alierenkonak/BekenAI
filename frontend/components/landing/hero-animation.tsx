'use client';

import { useEffect, useRef, useState } from 'react';
import { LogoMark } from '@/components/brand';
import { useInView, useReducedMotion } from '@/lib/hooks';

const LOOP = 140; // 100 ms ticks
const FINAL_FRAME = 110;

const SOURCES = [
  { n: '1', label: 'İş K. · md. 17', pre: 'bildirim şartına uymayan taraf, ', hit: 'bildirim süresine ilişkin ücret tutarında tazminat', post: ' ödemek zorundadır.' },
  { n: '2', label: '1475 s. K. · md. 14', pre: 'her geçen tam yıl için işverence işçiye ', hit: '30 günlük ücret tutarında kıdem tazminatı', post: ' ödenir.' },
  { n: '3', label: 'İş Mah. K. · md. 3', pre: '', hit: 'arabulucuya başvurulmuş olunması', post: ' dava şartıdır.' },
];

const CLAIMS = [
  { text: 'İşi üç yıldan fazla sürmüş işçi için bildirim süresi sekiz haftadır.', src: '1', ok: true },
  { text: 'Bildirime uymayan işveren, ihbar tazminatı ödemekle yükümlüdür.', src: '1', ok: true },
  { text: 'En az bir yıl çalışan işçiye her tam yıl için 30 günlük ücret tutarında kıdem tazminatı ödenir.', src: '2', ok: true },
  { text: 'İşveren ayrıca kötüniyet tazminatı da öder.', src: '3', ok: false },
];

const STEPS = ['Arama', 'Yazım', 'Doğrulama'];

// Character offset where each claim starts in the typing stream.
const CLAIM_STARTS = CLAIMS.map((_, index) =>
  CLAIMS.slice(0, index).reduce((sum, claim) => sum + claim.text.length, 0),
);

/**
 * Question → sources → drafting → claim verification, including a claim the sources do not
 * support: as in the app, it loses its citation and is marked, not deleted. Every element holds
 * its place from the first frame (untyped text is only invisible), so the card never changes
 * height and the page around it stays still.
 */
export function HeroAnimation() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref);
  const reduced = useReducedMotion();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!inView || reduced) return;
    const id = window.setInterval(() => setTick((value) => (value + 1) % LOOP), 100);
    return () => window.clearInterval(id);
  }, [inView, reduced]);

  const t = reduced ? FINAL_FRAME : tick;
  const phase = t < 18 ? 0 : t < 58 ? 1 : t < 94 ? 2 : 3;
  const typed = Math.max(0, (t - 18) * 8);
  const status =
    phase === 0
      ? { label: 'Kaynaklar aranıyor', cls: 'bg-accent-bg text-accent' }
      : phase === 1
        ? { label: 'Cevap yazılıyor', cls: 'bg-accent-bg text-accent' }
        : phase === 2
          ? { label: 'İddialar doğrulanıyor', cls: 'bg-accent-bg text-accent' }
          : { label: 'Doğrulandı', cls: 'bg-ok-bg text-ok' };

  const claims = CLAIMS.map((claim, index) => {
    const count = Math.max(0, Math.min(claim.text.length, typed - CLAIM_STARTS[index]));
    const complete = count >= claim.text.length;
    const verified = t >= 60 + index * 6;
    const rejected = !claim.ok && verified;
    return { ...claim, shown: claim.text.slice(0, count), rest: claim.text.slice(count), count, complete, verified, rejected };
  });

  return (
    <div
      ref={ref}
      role="img"
      aria-label="BekenAI’nin bir soruyu kaynaklarla cevaplayıp iddiaları tek tek doğrulamasını gösteren animasyon"
      className="flex w-full flex-col gap-3.5 overflow-hidden rounded-[18px] border border-line bg-surface p-5 shadow-lg sm:p-6"
    >
      <div className="flex items-center gap-4">
        {STEPS.map((label, index) => {
          const done = phase > index;
          const on = phase === index;
          return (
            <span
              key={label}
              className={`flex items-center gap-1.5 text-[12.5px] font-medium transition-colors ${on ? 'text-fg' : done ? 'text-fg2' : 'text-fg3'}`}
            >
              <span
                className={`flex size-[18px] items-center justify-center rounded-full border font-mono text-[10px] transition-colors ${
                  done ? 'border-ok bg-ok text-inv-fg' : on ? 'border-accent bg-accent-bg text-accent' : 'border-line text-fg3'
                }`}
              >
                {done ? '✓' : index + 1}
              </span>
              {label}
            </span>
          );
        })}
      </div>

      <div className="max-w-[440px] self-end rounded-[14px] bg-muted px-3.5 py-2.5 text-sm leading-normal">
        Dört yıllık işçi, bildirim süresi verilmeden çıkarıldı. Hangi alacaklar doğar?
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        {SOURCES.map((source, index) => {
          const on = t >= 3 + index * 4;
          return (
            <div
              key={source.n}
              className="flex flex-col gap-1.5 rounded-[10px] border border-line bg-bg px-3 py-2.5 transition-all duration-500"
              style={{ opacity: on ? 1 : 0, transform: `translateY(${on ? 0 : 8}px)` }}
            >
              <span className="flex items-center gap-1.5 font-mono text-[11px] text-accent">
                <span className="flex size-4 items-center justify-center rounded bg-accent-bg">{source.n}</span>
                {source.label}
              </span>
              <span className="text-xs leading-normal text-fg2">
                …{source.pre}
                <mark className="rounded-[3px] bg-mark px-0.5 text-fg">{source.hit}</mark>
                {source.post}
              </span>
            </div>
          );
        })}
      </div>
      <span
        className="font-mono text-[11px] text-fg3 transition-opacity duration-500"
        style={{ opacity: t >= 14 ? 1 : 0 }}
      >
        25 aday pasaj → yeniden sıralandı → 3 kaynak seçildi
      </span>

      <div className="flex flex-col gap-2.5 border-t border-line pt-3">
        <div className="flex items-center gap-2">
          <LogoMark size={20} />
          <span className="text-[13px] font-semibold">BekenAI</span>
          <span className={`flex h-[22px] items-center rounded-full px-2 text-[11.5px] font-medium transition-colors ${status.cls}`}>
            {status.label}
          </span>
        </div>
        {claims.map((claim) => (
          <div key={claim.text} className="flex items-start gap-3">
            <p className="m-0 grow text-sm leading-[1.55] text-fg">
              <span className={claim.rejected ? 'underline decoration-err/70 decoration-dashed decoration-1 underline-offset-[5px]' : ''}>
                {claim.shown}
              </span>
              {claim.count > 0 && !claim.complete && (
                // A zero-width anchor, so the cursor never pushes a word to the next line.
                <span className="relative">
                  <span className="absolute left-0.5 top-[-1px] h-[15px] w-[7px] bg-accent" />
                </span>
              )}
              <span className="invisible">{claim.rest}</span>
              {/* An unsupported claim's chip and its "doğrulanamadı" tag share one cell, so the swap keeps the width. */}
              <span className="ml-1 inline-grid align-[1px]">
                <span
                  className="inline-flex h-[18px] min-w-[18px] items-center justify-center justify-self-start rounded-[5px] border border-accent-line bg-accent-bg px-1 font-mono text-[10.5px] font-medium text-accent transition-opacity duration-300 [grid-area:1/1]"
                  style={{ opacity: claim.complete && !claim.rejected ? 1 : 0 }}
                >
                  {claim.src}
                </span>
                {!claim.ok && (
                  <span
                    className="inline-flex h-[18px] items-center rounded-[5px] border border-dashed border-err-line px-1.5 text-[10.5px] font-medium text-err transition-opacity duration-300 [grid-area:1/1]"
                    style={{ opacity: claim.rejected ? 1 : 0 }}
                  >
                    doğrulanamadı
                  </span>
                )}
              </span>
            </p>
            <span
              className={`flex h-[22px] shrink-0 items-center rounded-full px-2 text-[11.5px] font-medium transition-opacity ${
                claim.ok ? 'bg-ok-bg text-ok' : 'bg-err-bg text-err'
              }`}
              style={{ opacity: claim.verified ? 1 : 0 }}
            >
              {claim.ok ? '✓ Destekliyor' : '✕ Desteklenmiyor'}
            </span>
          </div>
        ))}
        <span className="text-[12.5px] text-fg2 transition-opacity duration-500" style={{ opacity: t >= 94 ? 1 : 0 }}>
          3 iddia doğrulandı · kaynakla desteklenmeyen 1 iddia işaretlendi
        </span>
      </div>
    </div>
  );
}
