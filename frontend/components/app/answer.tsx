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
import type { Messages } from '@/lib/i18n';
import { useI18n } from '@/lib/i18n/client';
import type {
  ConversationalAnswer,
  GenerationSummary,
  LegacyAnswer,
  ResearchSummary,
  StructuredAnswer,
  WebSearchOfferReason,
} from '@/lib/types';

const CHIP_TONE: Record<RenderedClaim['chips'][number]['channel'], { base: ChipTone; selected: ChipTone; partial: ChipTone }> = {
  primary: { base: 'primary', selected: 'selected', partial: 'partial' },
  doctrine: { base: 'doctrine', selected: 'doctrineSelected', partial: 'doctrine' },
  file: { base: 'file', selected: 'fileSelected', partial: 'filePartial' },
  web: { base: 'web', selected: 'webSelected', partial: 'webPartial' },
};

type ChipFacts = { label: string; channel: keyof Messages['answer']['chipNames']; partial: boolean; changed?: boolean };

/** The hover text of a citation chip: what its frame and dot mean. */
function chipTitle(chip: ChipFacts, m: Messages): string {
  const t = m.answer;
  const support = chip.partial ? t.chipPartial : t.chipSupports;
  return `${t.chipNames[chip.channel]} ${chip.label} · ${support}${chip.changed ? t.chipChanged : ''}. ${t.chipClick}`;
}

function chipAria(chip: ChipFacts, m: Messages): string {
  const t = m.answer;
  return `${t.chipNames[chip.channel]} ${chip.label}${chip.partial ? t.chipPartialAria : ''}${chip.changed ? t.chipChangedAria : ''}`;
}

function ClaimParagraph({
  claim,
  selectedSourceId,
  onSelect,
}: {
  claim: RenderedClaim;
  selectedSourceId: string | null;
  onSelect: (sourceId: string) => void;
}) {
  const { m } = useI18n();
  return (
    <p lang="tr" className="m-0 text-[15px] leading-[1.65] [text-wrap:pretty]">
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
            ariaLabel={chipAria(chip, m)}
            title={chipTitle(chip, m)}
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
  const { locale, m } = useI18n();
  return (
    <span>
      {sentence.unverified ? (
        <span
          title={m.answer.unverifiedTitle}
          className="underline decoration-err/70 decoration-dashed decoration-1 underline-offset-[5px]"
        >
          <InlineText text={sentence.text} />
        </span>
      ) : (
        <InlineText text={sentence.text} />
      )}
      {sentence.unverified && (
        <span
          lang={locale}
          className="ml-1.5 inline-flex h-[18px] items-center rounded-[5px] border border-dashed border-err-line px-1.5 align-[1px] text-[10.5px] font-medium text-err"
        >
          {m.answer.unverified}
        </span>
      )}
      <Chips chips={sentence.chips} selectedSourceId={selectedSourceId} onSelect={onSelect} />{' '}
    </span>
  );
}

function Chips({ chips, selectedSourceId, onSelect }: { chips: Chip[]; selectedSourceId: string | null; onSelect: (sourceId: string) => void }) {
  const { m } = useI18n();
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
            ariaLabel={chipAria(chip, m)}
            title={chipTitle(chip, m)}
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
  const { m } = useI18n();
  const t = m.answer;
  const [copied, setCopied] = useState(false);
  const count = (channel: string) => rendered.sources.filter((source) => source.channel === channel).length;
  const sourceSummary = [
    count('file') ? t.filePassages(count('file')) : null,
    count('primary') ? t.primarySources(count('primary')) : null,
    count('doctrine') ? t.doctrineSources(count('doctrine')) : null,
    count('web') ? t.webPages(count('web')) : null,
  ]
    .filter(Boolean)
    .join(' · ');
  const seconds = formatSeconds(generation?.latency_ms ?? null, m);
  const corpus = generation?.corpus_versions?.['labour_law:primary'];
  const index = generation?.index_versions?.['labour_law:primary'];
  // The badge speaks for the answer itself; the web section is labelled on its own.
  const answerSources = rendered.sources.filter((source) => source.channel !== 'web');
  const answerUnverified = rendered.blocks.some((block) => block.sentences.some((sentence) => sentence.unverified));
  const status =
    answer.answer_status === 'insufficient_evidence'
      ? { tone: 'neutral' as const, icon: 'searchX' as const, label: t.noSource }
      : answerUnverified
        ? { tone: 'neutral' as const, icon: 'alert' as const, label: t.partlyVerified }
        : answerSources.length > 0
          ? { tone: 'ok' as const, icon: 'shieldCheck' as const, label: t.verified }
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
      ...(answer.repeal_notice ? [answer.repeal_notice, ''] : []),
      text(rendered.blocks),
      ...(rendered.temporalChecks.length
        ? ['', t.copyCurrency, ...rendered.temporalChecks.map((check) => `- ${check.label ? `[${check.label}] ` : ''}${check.text}`)]
        : []),
      ...(answer.limitations.length ? ['', t.copyLimitations, ...answer.limitations.map((item) => `- ${item}`)] : []),
      ...(rendered.webBlocks.length ? ['', t.copyWeb, text(rendered.webBlocks)] : []),
      ...(rendered.sources.length
        ? [
            '',
            t.copySources,
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

      {answer.repeal_notice && (
        <p
          role="note"
          lang="tr"
          className="m-0 flex items-start gap-2 rounded-xl border border-err-line bg-err-bg px-3.5 py-2.5 text-[13.5px] leading-normal text-fg"
        >
          <Icon name="alert" size={15} className="mt-[3px] shrink-0 text-err" />
          <span>{answer.repeal_notice}</span>
        </p>
      )}

      <Blocks blocks={rendered.blocks} selectedSourceId={selectedSourceId} onSelect={onSelectSource} />

      {rendered.unverifiedCount > 0 && (
        <p className="m-0 flex items-start gap-2 rounded-xl border border-dashed border-err-line px-3.5 py-2.5 text-[12.5px] leading-normal text-fg2">
          <Icon name="alert" size={14} className="mt-0.5 shrink-0 text-err" />
          {t.unverifiedNote(rendered.unverifiedCount)}
        </p>
      )}

      {rendered.temporalChecks.length > 0 && (
        <TemporalChecks checks={rendered.temporalChecks} selectedSourceId={selectedSourceId} onSelect={onSelectSource} />
      )}

      {answer.limitations.length > 0 && (
        <div className="flex flex-col gap-1.5 rounded-xl bg-muted px-3.5 py-3">
          <span className="text-[12.5px] font-semibold text-fg2">{t.limitations}</span>
          <ul lang="tr" className="m-0 flex flex-col gap-1 pl-[18px] text-[13px] leading-normal text-fg2">
            {answer.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {rendered.webBlocks.length > 0 && (
        <section aria-label={t.webSection} className="flex flex-col gap-2.5 rounded-xl border border-web-line px-4 py-3.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px]">
            <Icon name="globe" size={14} className="text-web" />
            <span className="font-semibold text-web">{t.webHeading}</span>
            <span className="text-fg3">{t.webNote}</span>
          </div>
          <Blocks blocks={rendered.webBlocks} selectedSourceId={selectedSourceId} onSelect={onSelectSource} compact />
        </section>
      )}

      {answer.research && <ResearchDetails research={answer.research} />}

      {onWebSearch && <WebSearchOffer reason={answer.web_search_offer ?? 'no_sources'} onSearch={onWebSearch} busy={webSearchBusy} />}

      <div className="flex flex-wrap items-center gap-1">
        <button
          type="button"
          onClick={() => void copy()}
          className="flex h-7 items-center gap-1.5 rounded-[7px] px-2 text-[12.5px] text-fg2 hover:bg-hover hover:text-fg"
        >
          <Icon name={copied ? 'check' : 'copy'} size={14} />
          {copied ? m.common.copied : m.common.copy}
        </button>
        <span className="grow" />
        {corpus && (
          <span className="font-mono text-[11px] text-fg3" title={m.answer.versionTitle}>
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
    <div lang="tr" className={`flex flex-col [text-wrap:pretty] ${compact ? 'gap-2 text-[14px] leading-[1.65]' : 'gap-3 text-[15px] leading-[1.7]'}`}>
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
  const { m } = useI18n();
  const t = m.answer;
  return (
    <section aria-label={t.currency} className="flex flex-col gap-2 rounded-xl border border-line-strong px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px]">
        <Icon name="history" size={14} className="text-fg2" />
        <span className="font-semibold">{t.currency}</span>
        <span className="text-fg3">{t.currencyLead}</span>
      </div>
      <ul lang="tr" className="m-0 flex list-none flex-col gap-2 p-0 text-[13px] leading-normal text-fg2">
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
                  ariaLabel={t.sourceAria(check.label)}
                />
              )}
            </span>
          </li>
        ))}
      </ul>
      <p className="m-0 text-[12px] leading-normal text-fg3">
        {t.currencyNote}
      </p>
    </section>
  );
}

/** What a deep research covered: its parts, and how much it searched and read. */
function ResearchDetails({ research }: { research: ResearchSummary }) {
  const { m } = useI18n();
  const t = m.answer;
  const followed = research.followed_articles.length;
  return (
    <details className="group rounded-xl border border-line px-3.5 py-2.5 text-[13px] text-fg2">
      <summary className="flex cursor-pointer list-none items-center gap-2">
        <Icon name="search" size={14} className="text-accent" />
        <span className="font-semibold text-fg">{t.researchSummary}</span>
        <span className="text-fg3">{t.researchStats(research.parts.length, research.searches, research.passages, followed)}</span>
        <Icon name="chevDown" size={14} className="ml-auto shrink-0 transition-transform group-open:rotate-180" />
      </summary>
      <ol className="m-0 mt-2.5 flex flex-col gap-1 pl-5 leading-normal">
        {research.parts.map((part) => (
          <li key={part.question}>
            <span lang="tr">{part.question}</span> <span className="text-fg3">{t.researchSources(part.sources)}</span>
          </li>
        ))}
      </ol>
      {(research.follow_ups > 0 || followed > 0) && (
        <p className="m-0 mt-2 leading-normal text-fg3">
          {research.follow_ups > 0 ? t.researchFollowUps(research.follow_ups) : ''}
          {followed > 0 ? t.researchFollowed(research.followed_articles.join(', ')) : ''}
        </p>
      )}
    </details>
  );
}

/** Offered when a web search could help a legal question; never runs on its own. */
function WebSearchOffer({ reason, onSearch, busy }: { reason: WebSearchOfferReason; onSearch: () => void; busy: boolean }) {
  const { m } = useI18n();
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line px-3.5 py-3 sm:flex-row sm:items-center">
      <p className="m-0 grow text-[13px] leading-normal text-fg2">
        {m.answer.webOffer[reason]}
        {m.answer.webOfferSuffix}
      </p>
      <button
        type="button"
        onClick={onSearch}
        disabled={busy}
        className="flex h-[34px] w-fit shrink-0 items-center gap-1.5 rounded-[9px] border border-web-line bg-web-bg px-3.5 text-[13.5px] font-medium text-web hover:border-web disabled:opacity-60"
      >
        <Icon name="globe" size={15} />
        {m.answer.searchWeb}
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
  const { m } = useI18n();
  const t = m.answer;
  const [copied, setCopied] = useState(false);
  const count = (channel: string) => rendered.sources.filter((source) => source.channel === channel).length;
  const fileCount = count('file');
  const primaryCount = count('primary');
  const doctrineCount = count('doctrine');
  const sourceSummary = [
    fileCount ? t.filePassages(fileCount) : null,
    primaryCount ? (doctrineCount || fileCount ? t.primaryShort(primaryCount) : t.primarySources(primaryCount)) : null,
    doctrineCount ? t.doctrineSources(doctrineCount) : null,
  ]
    .filter(Boolean)
    .join(' · ');
  const seconds = formatSeconds(generation?.latency_ms ?? null, m);
  const corpus = generation?.corpus_versions?.['labour_law:primary'];
  const index = generation?.index_versions?.['labour_law:primary'];

  const copy = async () => {
    const lines = [
      ...(rendered.file.length ? [t.copyFile, ...rendered.file.map((claim) => claim.text), ''] : []),
      ...(rendered.file.length && rendered.primary.length ? [t.copyPrimary] : []),
      ...rendered.primary.map((claim) => claim.text),
      ...(rendered.doctrine.length ? ['', t.copyDoctrine, ...rendered.doctrine.map((claim) => claim.text)] : []),
      ...(answer.limitations.length ? ['', t.copyLimitations, ...answer.limitations.map((item) => `- ${item}`)] : []),
      '',
      t.copySources,
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
          {t.verified}
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
            <span className="font-semibold">{t.fileHeading}</span>
            <span className="text-fg3">{t.fileNote}</span>
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
              <span className="font-semibold">{t.primaryHeading}</span>
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
            <span className="font-semibold">{t.doctrineHeading}</span>
            <span className="text-fg3">{t.doctrineNote}</span>
          </div>
          {rendered.doctrine.map((claim) => (
            <ClaimParagraph key={claim.number} claim={claim} selectedSourceId={selectedSourceId} onSelect={onSelectSource} />
          ))}
        </div>
      )}

      {answer.limitations.length > 0 && (
        <div className="flex flex-col gap-1.5 rounded-xl bg-muted px-3.5 py-3">
          <span className="text-[12.5px] font-semibold text-fg2">{t.limitations}</span>
          <ul lang="tr" className="m-0 flex flex-col gap-1 pl-[18px] text-[13px] leading-normal text-fg2">
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
          {copied ? m.common.copied : m.common.copy}
        </button>
        <span className="grow" />
        {corpus && (
          <span className="font-mono text-[11px] text-fg3" title={m.answer.versionTitle}>
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
  const { m } = useI18n();
  const t = m.answer;
  return (
    <StateCard
      icon="searchX"
      tone="neutral"
      title={t.insufficientTitle}
      action={
        <button type="button" onClick={onEdit} className={secondaryButton}>
          {t.editQuestion}
        </button>
      }
    >
      {t.insufficientBody}
      {reason && (
        <span className="mt-1.5 block text-[12.5px] text-fg3">
          {t.insufficientReason} <span lang="tr">{reason}</span>
        </span>
      )}
    </StateCard>
  );
}

export function FailedCard({ code, onRetry }: { code: string | null; onRetry: () => void }) {
  const { m } = useI18n();
  const retryable = isRetryableFailure(code);
  return (
    <StateCard
      icon="alert"
      tone="err"
      title={m.answer.failedTitle}
      action={
        <button
          type="button"
          onClick={onRetry}
          className="flex h-[34px] w-fit items-center gap-1.5 rounded-[9px] bg-inv px-3.5 text-[13.5px] font-medium text-inv-fg"
        >
          <Icon name="refresh" size={14} strokeWidth={1.9} />
          {retryable ? m.common.retry : m.answer.resend}
        </button>
      }
    >
      {describeError(code ?? 'job_failed', m)} {m.answer.failedSaved}
    </StateCard>
  );
}

export function CancelledCard({ onResend }: { onResend: () => void }) {
  const { m } = useI18n();
  return (
    <StateCard
      icon="stop"
      tone="muted"
      title={m.answer.cancelledTitle}
      action={
        <button type="button" onClick={onResend} className={secondaryButton}>
          {m.answer.resend}
        </button>
      }
    >
      {m.answer.cancelledBody}
    </StateCard>
  );
}
