'use client';

import { useState } from 'react';
import { LogoMark } from '@/components/brand';
import { Icon } from '@/components/icons';
import { Badge, CitationChip, type ChipTone } from '@/components/ui';
import {
  isConversational,
  type Chip,
  type RenderedAnswer,
  type RenderedClaim,
  type RenderedConversation,
  type RenderedLegacyAnswer,
  type RenderedSentence,
  type RenderedTemporalCheck,
} from '@/lib/answer';
import { describeError, formatSeconds, isRetryableFailure } from '@/lib/format';
import type { ConversationalAnswer, GenerationSummary, LegacyAnswer, StructuredAnswer, WebSearchOfferReason } from '@/lib/types';

const CHIP_TONE: Record<RenderedClaim['chips'][number]['channel'], { base: ChipTone; selected: ChipTone; partial: ChipTone }> = {
  primary: { base: 'primary', selected: 'selected', partial: 'partial' },
  doctrine: { base: 'doctrine', selected: 'doctrineSelected', partial: 'doctrine' },
  file: { base: 'file', selected: 'fileSelected', partial: 'filePartial' },
  web: { base: 'web', selected: 'webSelected', partial: 'webPartial' },
};

const CHIP_NAME = { primary: 'Kaynak', doctrine: 'Doktrin kaynağı', file: 'Dosya pasajı', web: 'Web kaynağı' } as const;

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
  onWebSearch,
  webSearchBusy = false,
}: {
  answer: StructuredAnswer;
  rendered: RenderedAnswer;
  generation: GenerationSummary | null;
  selectedSourceId: string | null;
  onSelectSource: (sourceId: string) => void;
  /** Set when this answer may be retried as a web search; the offer is hidden otherwise. */
  onWebSearch?: () => void;
  webSearchBusy?: boolean;
}) {
  if (rendered.kind === 'conversational' && isConversational(answer)) {
    return (
      <ConversationalAnswerView
        answer={answer}
        rendered={rendered}
        generation={generation}
        selectedSourceId={selectedSourceId}
        onSelectSource={onSelectSource}
        onWebSearch={onWebSearch}
        webSearchBusy={webSearchBusy}
      />
    );
  }
  if (rendered.kind === 'legacy' && !isConversational(answer)) {
    return (
      <LegacyAnswerView answer={answer} rendered={rendered} generation={generation} selectedSourceId={selectedSourceId} onSelectSource={onSelectSource} />
    );
  }
  return null;
}

/** Renders **bold** spans the model sometimes uses; everything else stays plain text. */
function InlineText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith('**') && part.endsWith('**') && part.length > 4 ? <strong key={index}>{part.slice(2, -2)}</strong> : part,
      )}
    </>
  );
}

function Sentence({
  sentence,
  selectedSourceId,
  onSelect,
}: {
  sentence: RenderedSentence;
  selectedSourceId: string | null;
  onSelect: (sourceId: string) => void;
}) {
  return (
    <span>
      {sentence.unverified ? (
        <span
          title="Bu ifade kaynaklarla doğrulanamadı"
          className="underline decoration-err/70 decoration-dashed decoration-1 underline-offset-[5px]"
        >
          <InlineText text={sentence.text} />
        </span>
      ) : (
        <InlineText text={sentence.text} />
      )}
      {sentence.unverified && (
        <span className="ml-1.5 inline-flex h-[18px] items-center rounded-[5px] border border-dashed border-err-line px-1.5 align-[1px] text-[10.5px] font-medium text-err">
          doğrulanamadı
        </span>
      )}
      <Chips chips={sentence.chips} selectedSourceId={selectedSourceId} onSelect={onSelect} />{' '}
    </span>
  );
}

function Chips({ chips, selectedSourceId, onSelect }: { chips: Chip[]; selectedSourceId: string | null; onSelect: (sourceId: string) => void }) {
  return (
    <>
      {chips.map((chip) => {
        const tones = CHIP_TONE[chip.channel];
        const tone = chip.sourceId === selectedSourceId ? tones.selected : chip.partial ? tones.partial : tones.base;
        return (
          <CitationChip
            key={chip.sourceId}
            label={chip.label}
            tone={tone}
            flagged={chip.changed}
            onClick={() => onSelect(chip.sourceId)}
            ariaLabel={`${CHIP_NAME[chip.channel]} ${chip.label}${chip.partial ? ', kısmen destekliyor' : ''}${chip.changed ? ', yürürlük uyarısı var' : ''}`}
          />
        );
      })}
    </>
  );
}

function ConversationalAnswerView({
  answer,
  rendered,
  generation,
  selectedSourceId,
  onSelectSource,
  onWebSearch,
  webSearchBusy,
}: {
  answer: ConversationalAnswer;
  rendered: RenderedConversation;
  generation: GenerationSummary | null;
  selectedSourceId: string | null;
  onSelectSource: (sourceId: string) => void;
  onWebSearch?: () => void;
  webSearchBusy: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const count = (channel: string) => rendered.sources.filter((source) => source.channel === channel).length;
  const sourceSummary = [
    count('file') ? `${count('file')} dosya pasajı` : null,
    count('primary') ? `${count('primary')} birincil kaynak` : null,
    count('doctrine') ? `${count('doctrine')} doktrin kaynağı` : null,
    count('web') ? `${count('web')} web sayfası` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  const seconds = formatSeconds(generation?.latency_ms ?? null);
  const corpus = generation?.corpus_versions?.['labour_law:primary'];
  const index = generation?.index_versions?.['labour_law:primary'];
  // The badge speaks for the answer itself; the web section is labelled on its own.
  const answerSources = rendered.sources.filter((source) => source.channel !== 'web');
  const answerUnverified = rendered.blocks.some((block) => block.sentences.some((sentence) => sentence.unverified));
  const status =
    answer.answer_status === 'insufficient_evidence'
      ? { tone: 'neutral' as const, icon: 'searchX' as const, label: 'Kaynak bulunamadı' }
      : answerUnverified
        ? { tone: 'neutral' as const, icon: 'alert' as const, label: 'Kısmen doğrulandı' }
        : answerSources.length > 0
          ? { tone: 'ok' as const, icon: 'shieldCheck' as const, label: 'Doğrulandı' }
          : null;

  const copy = async () => {
    const text = (blocks: RenderedConversation['blocks']) =>
      blocks
        .map((block) =>
          block.kind === 'bullets'
            ? block.sentences.map((sentence) => `- ${sentence.text} ${sentence.chips.map((chip) => `[${chip.label}]`).join('')}`.trimEnd()).join('\n')
            : block.sentences.map((sentence) => `${sentence.text}${sentence.chips.map((chip) => ` [${chip.label}]`).join('')}`).join(' '),
        )
        .join('\n\n');
    const lines = [
      text(rendered.blocks),
      ...(rendered.temporalChecks.length
        ? ['', 'Yürürlük kontrolü:', ...rendered.temporalChecks.map((check) => `- ${check.label ? `[${check.label}] ` : ''}${check.text}`)]
        : []),
      ...(answer.limitations.length ? ['', 'Sınırlamalar:', ...answer.limitations.map((item) => `- ${item}`)] : []),
      ...(rendered.webBlocks.length ? ['', 'Web araması (resmî kaynak değildir):', text(rendered.webBlocks)] : []),
      ...(rendered.sources.length
        ? [
            '',
            'Kaynaklar:',
            ...rendered.sources.map(
              (source) =>
                `[${source.label}] ${source.snapshot.title}${source.snapshot.location_label ? `, ${source.snapshot.location_label}` : ''}${source.snapshot.breadcrumb.length ? ` — ${source.snapshot.breadcrumb.join(' › ')}` : ''}${source.channel === 'web' && source.snapshot.source_url ? ` — ${source.snapshot.source_url}` : ''}`,
            ),
          ]
        : []),
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
    <article className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <LogoMark size={22} />
        <span className="text-[13.5px] font-semibold">BekenAI</span>
        {status && (
          <Badge tone={status.tone}>
            <Icon name={status.icon} size={13} strokeWidth={2} />
            {status.label}
          </Badge>
        )}
        <span className="text-[12.5px] text-fg3">
          {sourceSummary}
          {sourceSummary && seconds ? ' · ' : ''}
          {seconds}
        </span>
      </div>

      <Blocks blocks={rendered.blocks} selectedSourceId={selectedSourceId} onSelect={onSelectSource} />

      {rendered.unverifiedCount > 0 && (
        <p className="m-0 flex items-start gap-2 rounded-xl border border-dashed border-err-line px-3.5 py-2.5 text-[12.5px] leading-normal text-fg2">
          <Icon name="alert" size={14} className="mt-0.5 shrink-0 text-err" />
          {rendered.unverifiedCount === 1 ? 'Bir ifade' : `${rendered.unverifiedCount} ifade`} kaynaklarla doğrulanamadı. İşaretli
          cümleleri bir kaynağa bakmadan kullanmayın.
        </p>
      )}

      {rendered.temporalChecks.length > 0 && (
        <TemporalChecks checks={rendered.temporalChecks} selectedSourceId={selectedSourceId} onSelect={onSelectSource} />
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

      {rendered.webBlocks.length > 0 && (
        <section aria-label="Web araması" className="flex flex-col gap-2.5 rounded-xl border border-web-line px-4 py-3.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px]">
            <Icon name="globe" size={14} className="text-web" />
            <span className="font-semibold text-web">Web&apos;de ne deniyor?</span>
            <span className="text-fg3">Resmî kaynak değildir; yukarıdaki cevaptan ayrı değerlendirin.</span>
          </div>
          <Blocks blocks={rendered.webBlocks} selectedSourceId={selectedSourceId} onSelect={onSelectSource} compact />
        </section>
      )}

      {onWebSearch && <WebSearchOffer reason={answer.web_search_offer ?? 'no_sources'} onSearch={onWebSearch} busy={webSearchBusy} />}

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

function Blocks({
  blocks,
  selectedSourceId,
  onSelect,
  compact = false,
}: {
  blocks: RenderedConversation['blocks'];
  selectedSourceId: string | null;
  onSelect: (sourceId: string) => void;
  compact?: boolean;
}) {
  return (
    <div className={`flex flex-col [text-wrap:pretty] ${compact ? 'gap-2 text-[14px] leading-[1.65]' : 'gap-3 text-[15px] leading-[1.7]'}`}>
      {blocks.map((block, blockIndex) => {
        if (block.kind === 'heading') {
          return (
            <h3 key={blockIndex} className="m-0 mt-1.5 text-[15.5px] font-semibold leading-snug">
              {block.sentences.map((sentence) => sentence.text).join(' ')}
            </h3>
          );
        }
        if (block.kind === 'bullets') {
          return (
            <ul key={blockIndex} className="m-0 flex list-disc flex-col gap-1.5 pl-5 marker:text-fg3">
              {block.sentences.map((sentence) => (
                <li key={sentence.number}>
                  <Sentence sentence={sentence} selectedSourceId={selectedSourceId} onSelect={onSelect} />
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={blockIndex} className="m-0">
            {block.sentences.map((sentence) => (
              <Sentence key={sentence.number} sentence={sentence} selectedSourceId={selectedSourceId} onSelect={onSelect} />
            ))}
          </p>
        );
      })}
    </div>
  );
}

/**
 * Yürürlük kontrolü: which cited provisions read differently on the case date. Built by
 * code from the official amendment notes, never written by the model.
 */
function TemporalChecks({
  checks,
  selectedSourceId,
  onSelect,
}: {
  checks: RenderedTemporalCheck[];
  selectedSourceId: string | null;
  onSelect: (sourceId: string) => void;
}) {
  return (
    <section aria-label="Yürürlük kontrolü" className="flex flex-col gap-2 rounded-xl border border-line-strong px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px]">
        <Icon name="history" size={14} className="text-fg2" />
        <span className="font-semibold">Yürürlük kontrolü</span>
        <span className="text-fg3">Atıf yapılan hükümlerin ve kararların güncelliği</span>
      </div>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[13px] leading-normal text-fg2">
        {checks.map((check) => (
          <li key={`${check.sourceId}:${check.text}`} className="flex gap-2">
            <Icon
              name={check.level === 'near_change' ? 'history' : 'alert'}
              size={14}
              className={`mt-[3px] shrink-0 ${check.level === 'near_change' ? 'text-fg3' : 'text-err'}`}
            />
            <span>
              {check.text}
              {check.label && (
                <CitationChip
                  label={check.label}
                  tone={check.sourceId === selectedSourceId ? 'selected' : 'primary'}
                  onClick={() => onSelect(check.sourceId)}
                  ariaLabel={`Kaynak ${check.label}`}
                />
              )}
            </span>
          </li>
        ))}
      </ul>
      <p className="m-0 text-[12px] leading-normal text-fg3">
        Değişiklikten önceki metin BekenAI&apos;nin kaynaklarında yok; mevzuat.gov.tr&apos;den ya da ilgili Resmî Gazete&apos;den kontrol
        edin.
      </p>
    </section>
  );
}

const WEB_OFFER_TEXT: Record<WebSearchOfferReason, string> = {
  no_sources: "BekenAI'nin kaynaklarında bu soruya dayanak bulunamadı. İsterseniz web'de de arayabilirim;",
  provision_changed:
    "Atıf yapılan bir hüküm olay tarihinden sonra değişmiş ve eski metni BekenAI'nin kaynaklarında yok. İsterseniz sorunuzu web'de bu hükmün eski haliyle birlikte arayabilirim;",
  missing_info: "Bu cevap için gereken bazı bilgiler BekenAI'nin kaynaklarında yok. İsterseniz web'de de arayabilirim;",
};

/** Offered when a web search could help a legal question; never runs on its own. */
function WebSearchOffer({ reason, onSearch, busy }: { reason: WebSearchOfferReason; onSearch: () => void; busy: boolean }) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line px-3.5 py-3 sm:flex-row sm:items-center">
      <p className="m-0 grow text-[13px] leading-normal text-fg2">
        {WEB_OFFER_TEXT[reason]} bulunanlar cevabın sonuna ayrı ve etiketli bir bölüm olarak eklenir.
      </p>
      <button
        type="button"
        onClick={onSearch}
        disabled={busy}
        className="flex h-[34px] w-fit shrink-0 items-center gap-1.5 rounded-[9px] border border-web-line bg-web-bg px-3.5 text-[13.5px] font-medium text-web hover:border-web disabled:opacity-60"
      >
        <Icon name="globe" size={15} />
        Web&apos;de ara
      </button>
    </div>
  );
}

function LegacyAnswerView({
  answer,
  rendered,
  generation,
  selectedSourceId,
  onSelectSource,
}: {
  answer: LegacyAnswer;
  rendered: RenderedLegacyAnswer;
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
