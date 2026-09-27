'use client';

import { useState } from 'react';
import { LogoMark } from '@/components/brand';
import { Icon } from '@/components/icons';
import { Badge, CitationChip, type ChipTone } from '@/components/ui';
import type { RenderedAnswer, RenderedClaim } from '@/lib/answer';
import { describeError, formatSeconds, isRetryableFailure } from '@/lib/format';
import type { GenerationSummary, StructuredAnswer } from '@/lib/types';

const CHIP_TONE: Record<RenderedClaim['chips'][number]['channel'], { base: ChipTone; selected: ChipTone; partial: ChipTone }> = {
  primary: { base: 'primary', selected: 'selected', partial: 'partial' },
  doctrine: { base: 'doctrine', selected: 'doctrineSelected', partial: 'doctrine' },
  file: { base: 'file', selected: 'fileSelected', partial: 'filePartial' },
};

const CHIP_NAME = { primary: 'Kaynak', doctrine: 'Doktrin kaynağı', file: 'Dosya pasajı' } as const;

function ClaimParagraph({
  claim,
  selectedSourceId,
  onSelect,
}: {
  claim: RenderedClaim;
  selectedSourceId: string | null;
  onSelect: (sourceId: string) => void;
}) {
  return (
    <p className="m-0 text-[15px] leading-[1.65] [text-wrap:pretty]">
      {claim.text}
      {claim.chips.map((chip) => {
        const tones = CHIP_TONE[chip.channel];
        const tone = chip.sourceId === selectedSourceId ? tones.selected : chip.partial ? tones.partial : tones.base;
        return (
          <CitationChip
            key={chip.sourceId}
            label={chip.label}
            tone={tone}
            onClick={() => onSelect(chip.sourceId)}
            ariaLabel={`${CHIP_NAME[chip.channel]} ${chip.label}${chip.partial ? ', kısmen destekliyor' : ''}`}
          />
        );
      })}
    </p>
  );
}

export function AnswerView({
  answer,
  rendered,
  generation,
  selectedSourceId,
  onSelectSource,
}: {
  answer: StructuredAnswer;
  rendered: RenderedAnswer;
  generation: GenerationSummary | null;
  selectedSourceId: string | null;
  onSelectSource: (sourceId: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const count = (channel: string) => rendered.sources.filter((source) => source.channel === channel).length;
  const fileCount = count('file');
  const primaryCount = count('primary');
  const doctrineCount = count('doctrine');
  const sourceSummary = [
    fileCount ? `${fileCount} dosya pasajı` : null,
    primaryCount ? `${primaryCount} birincil${doctrineCount || fileCount ? '' : ' kaynak'}` : null,
    doctrineCount ? `${doctrineCount} doktrin kaynağı` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  const seconds = formatSeconds(generation?.latency_ms ?? null);
  const corpus = generation?.corpus_versions?.['labour_law:primary'];
  const index = generation?.index_versions?.['labour_law:primary'];

  const copy = async () => {
    const lines = [
      ...(rendered.file.length ? ['Dosyadaki bilgiler:', ...rendered.file.map((claim) => claim.text), ''] : []),
      ...(rendered.file.length && rendered.primary.length ? ['Mevzuat ve içtihat:'] : []),
      ...rendered.primary.map((claim) => claim.text),
      ...(rendered.doctrine.length ? ['', 'Doktrin ve yardımcı kaynaklar:', ...rendered.doctrine.map((claim) => claim.text)] : []),
      ...(answer.limitations.length ? ['', 'Sınırlamalar:', ...answer.limitations.map((item) => `- ${item}`)] : []),
      '',
      'Kaynaklar:',
      ...rendered.sources.map(
        (source) =>
          `[${source.label}] ${source.snapshot.title}${source.snapshot.location_label ? `, ${source.snapshot.location_label}` : ''}${source.snapshot.breadcrumb.length ? ` — ${source.snapshot.breadcrumb.join(' › ')}` : ''}`,
      ),
    ];
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <article className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <LogoMark size={22} />
        <span className="text-[13.5px] font-semibold">BekenAI</span>
        <Badge tone="ok">
          <Icon name="shieldCheck" size={13} strokeWidth={2} />
          Doğrulandı
        </Badge>
        <span className="text-[12.5px] text-fg3">
          {sourceSummary}
          {seconds ? ` · ${seconds}` : ''}
        </span>
      </div>

      {rendered.file.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
            <span className="size-2 rounded-[2px] bg-file" />
            <span className="font-semibold">Dosyadaki bilgiler</span>
            <span className="text-fg3">Yüklediğiniz belgelerde yazanlar; hukuki değerlendirme değildir</span>
          </div>
          {rendered.file.map((claim) => (
            <ClaimParagraph key={claim.number} claim={claim} selectedSourceId={selectedSourceId} onSelect={onSelectSource} />
          ))}
        </div>
      )}

      {rendered.primary.length > 0 && (
        <div className={`flex flex-col gap-2.5 ${rendered.file.length ? 'border-t border-line pt-3.5' : ''}`}>
          {rendered.file.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <span className="size-2 rounded-[2px] bg-accent" />
              <span className="font-semibold">Mevzuat ve içtihat</span>
            </div>
          )}
          {rendered.primary.map((claim) => (
            <ClaimParagraph key={claim.number} claim={claim} selectedSourceId={selectedSourceId} onSelect={onSelectSource} />
          ))}
        </div>
      )}

      {rendered.doctrine.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-line pt-3.5">
          <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
            <span className="size-2 rounded-[2px] bg-doc" />
            <span className="font-semibold">Doktrin ve yardımcı kaynaklar</span>
            <span className="text-fg3">Birincil kaynaklardan ayrı değerlendirilir</span>
          </div>
          {rendered.doctrine.map((claim) => (
            <ClaimParagraph key={claim.number} claim={claim} selectedSourceId={selectedSourceId} onSelect={onSelectSource} />
          ))}
        </div>
      )}

      {answer.limitations.length > 0 && (
        <div className="flex flex-col gap-1.5 rounded-xl bg-muted px-3.5 py-3">
          <span className="text-[12.5px] font-semibold text-fg2">Sınırlamalar</span>
          <ul className="m-0 flex flex-col gap-1 pl-[18px] text-[13px] leading-normal text-fg2">
            {answer.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1">
        <button
          type="button"
          onClick={() => void copy()}
          className="flex h-7 items-center gap-1.5 rounded-[7px] px-2 text-[12.5px] text-fg2 hover:bg-hover hover:text-fg"
        >
          <Icon name={copied ? 'check' : 'copy'} size={14} />
          {copied ? 'Kopyalandı' : 'Kopyala'}
        </button>
        <span className="grow" />
        {corpus && (
          <span className="font-mono text-[11px] text-fg3" title="Cevabın üretildiği kaynak ve dizin sürümü">
            {corpus}
            {index ? ` · ${index}` : ''}
          </span>
        )}
      </div>
    </article>
  );
}

function StateCard({
  icon,
  tone,
  title,
  children,
  action,
}: {
  icon: 'searchX' | 'alert' | 'stop';
  tone: 'neutral' | 'err' | 'muted';
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  const frame = {
    neutral: 'border-line bg-surface',
    err: 'border-err-line bg-err-bg',
    muted: 'border-dashed border-line-strong bg-transparent',
  }[tone];
  return (
    <div role={tone === 'err' ? 'alert' : undefined} className={`flex flex-col gap-3 rounded-[14px] border p-5 ${frame}`}>
      <span
        className={`flex size-[34px] items-center justify-center rounded-[10px] ${tone === 'err' ? 'bg-surface text-err' : 'bg-muted text-fg2'}`}
      >
        <Icon name={icon} size={18} />
      </span>
      <h3 className={`m-0 text-[15px] font-semibold leading-snug ${tone === 'muted' ? 'text-fg2' : ''}`}>{title}</h3>
      <div className="text-[13.5px] leading-relaxed text-fg2">{children}</div>
      {action}
    </div>
  );
}

const secondaryButton =
  'flex h-[34px] w-fit items-center gap-1.5 rounded-[9px] border border-line-strong bg-surface px-3.5 text-[13.5px] font-medium text-fg hover:bg-hover';

export function InsufficientCard({ reason, onEdit }: { reason: string | null; onEdit: () => void }) {
  return (
    <StateCard
      icon="searchX"
      tone="neutral"
      title="Bu soruyu destekleyen birincil kaynak bulunamadı"
      action={
        <button type="button" onClick={onEdit} className={secondaryButton}>
          Soruyu düzenle
        </button>
      }
    >
      BekenAI yalnızca doğrulanabilen kaynaklarla cevap verir. Soruyu somutlaştırmayı ya da ilgili kanun maddesini belirtmeyi deneyin.
      {reason && <span className="mt-1.5 block text-[12.5px] text-fg3">Gerekçe: {reason}</span>}
    </StateCard>
  );
}

export function FailedCard({ code, onRetry }: { code: string | null; onRetry: () => void }) {
  const retryable = isRetryableFailure(code);
  return (
    <StateCard
      icon="alert"
      tone="err"
      title="Cevap şu an oluşturulamadı"
      action={
        <button
          type="button"
          onClick={onRetry}
          className="flex h-[34px] w-fit items-center gap-1.5 rounded-[9px] bg-inv px-3.5 text-[13.5px] font-medium text-inv-fg"
        >
          <Icon name="refresh" size={14} strokeWidth={1.9} />
          {retryable ? 'Tekrar dene' : 'Yeniden gönder'}
        </button>
      }
    >
      {describeError(code ?? 'job_failed')} Sorunuz kaydedildi; tekrar denediğinizde yeniden işlenir.
    </StateCard>
  );
}

export function CancelledCard({ onResend }: { onResend: () => void }) {
  return (
    <StateCard
      icon="stop"
      tone="muted"
      title="Cevap üretimi iptal edildi"
      action={
        <button type="button" onClick={onResend} className={secondaryButton}>
          Yeniden gönder
        </button>
      }
    >
      Bu soru için kaynak araması ve cevap üretimi durduruldu.
    </StateCard>
  );
}
