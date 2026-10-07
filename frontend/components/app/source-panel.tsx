'use client';

import { useState, type ReactNode } from 'react';
import { Icon } from '@/components/icons';
import { Badge } from '@/components/ui';
import { api } from '@/lib/api';
import { sourceKind, sourceSubtitle, type SourceRef } from '@/lib/answer';
import { describeError, formatDate } from '@/lib/format';
import { useI18n } from '@/lib/i18n/client';
import type { ProvisionChange } from '@/lib/types';

/** Official amendment notes, newest first: a law passage's own, or those of a decision's articles. */
function ProvisionHistory({ changes, title }: { changes: ProvisionChange[]; title: string }) {
  const { m } = useI18n();
  const t = m.panel;
  return (
    <div className="flex flex-col gap-2 rounded-[10px] border border-line px-3.5 py-3">
      <div className="flex items-center gap-2 text-[12.5px]">
        <Icon name="history" size={14} className="text-fg2" />
        <span className="font-semibold">{title}</span>
      </div>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {changes.map((change) => (
          <li key={`${change.change_date}:${change.provision}:${change.annotation}`} className="flex gap-3 text-[12.5px] leading-normal">
            <span className="w-[74px] shrink-0 font-mono text-[11.5px] text-fg3">
              {formatDate(change.change_date, m)}
            </span>
            <span className="text-fg2">
              <span className="font-medium text-fg">
                {t.changes[change.event_type]}
                {change.provision ? ` · ${change.provision}` : ''}
              </span>
              {change.amending_law ? t.amendingLaw(change.amending_law) : ''}
              <span lang="tr" className="block text-fg3">
                {change.annotation}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <p className="m-0 text-[12px] leading-normal text-fg3">
        {t.historyNote}
      </p>
    </div>
  );
}

export function SourcePanel({
  selected,
  sources,
  onSelect,
  onClose,
  warnings = [],
}: {
  selected: SourceRef;
  sources: SourceRef[];
  onSelect: (sourceId: string) => void;
  onClose: () => void;
  /** The answer's Yürürlük kontrolü notes about this source (the red dot on its chip). */
  warnings?: { level: string; text: string }[];
}) {
  const { m } = useI18n();
  const t = m.panel;
  const [copied, setCopied] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  const { snapshot } = selected;
  const doctrine = selected.channel === 'doctrine';
  const file = selected.channel === 'file';
  const web = selected.channel === 'web';
  const tone = file
    ? { solid: 'bg-file', soft: 'bg-file-bg text-file' }
    : doctrine
      ? { solid: 'bg-doc', soft: 'bg-doc-bg text-doc' }
      : web
        ? { solid: 'bg-web', soft: 'bg-web-bg text-web' }
        : { solid: 'bg-accent', soft: 'bg-accent-bg text-accent' };
  const kind = file
    ? `${t.kindFile}${snapshot.location_label ? ` · ${snapshot.location_label}` : ''}`
    : doctrine
      ? t.kindDoctrine
      : web
        ? t.kindWeb
        : `${t.kindPrimary} · ${sourceKind(snapshot, selected.channel, m)}`;
  const allPartial = selected.claims.every((claim) => claim.status === 'partial');
  const claimNumbers = selected.claims.map((claim) => claim.number).join(', ');
  const others = sources.filter((source) => source.sourceId !== selected.sourceId);

  // Signed links live for a minute, so one is fetched per click. The tab opens first,
  // inside the click, so popup blockers let it through.
  const openFile = async () => {
    if (!snapshot.file_id) return;
    setOpenError(null);
    const tab = window.open('', '_blank');
    try {
      const { url } = await api.downloadUrl(snapshot.file_id);
      const page = snapshot.title.toLowerCase().endsWith('.pdf') && snapshot.page_number ? `#page=${snapshot.page_number}` : '';
      if (tab) {
        tab.opener = null;
        tab.location.href = url + page;
      } else {
        window.location.assign(url + page);
      }
    } catch (error) {
      tab?.close();
      setOpenError(describeError(error, m));
    }
  };

  const copyPassage = async () => {
    try {
      const where = [snapshot.location_label, ...snapshot.breadcrumb, web ? snapshot.source_url : null].filter(Boolean).join(', ');
      await navigator.clipboard.writeText(`${snapshot.exact_passage}\n\n— ${snapshot.title}${where ? `, ${where}` : ''}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line pl-5 pr-4">
        <h2 className="m-0 text-sm font-semibold">{t.sources}</h2>
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 text-[11.5px] font-medium text-fg2">
          {sources.length}
        </span>
        <span className="grow" />
        <button
          type="button"
          onClick={onClose}
          aria-label={t.close}
          className="flex size-8 items-center justify-center rounded-lg text-fg3 hover:bg-hover hover:text-fg"
        >
          <Icon name="x" />
        </button>
      </header>

      <div className="flex min-h-0 grow flex-col gap-[18px] overflow-y-auto p-5">
        <section className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span
              className={`flex h-[19px] min-w-5 items-center justify-center rounded-[5px] px-[5px] font-mono text-[11px] font-medium text-inv-fg ${tone.solid}`}
            >
              {selected.label}
            </span>
            <span className={`flex h-[22px] items-center rounded-md px-2 text-xs font-medium ${tone.soft}`}>{kind}</span>
            {allPartial && (
              <span className="flex h-[22px] items-center rounded-md border border-dashed border-line-strong px-2 text-xs text-fg2">{t.partly}</span>
            )}
          </div>
          {warnings.length > 0 && (
            <div className="flex flex-col gap-1.5 rounded-[10px] border border-err-line bg-err-bg px-3.5 py-3">
              <span className="flex items-center gap-2 text-[12.5px] font-semibold text-err">
                <span aria-hidden className="size-[7px] rounded-full bg-err" />
                {t.warning}
              </span>
              {warnings.map((warning) => (
                <p key={warning.text} lang="tr" className="m-0 text-[12.5px] leading-normal text-fg2">
                  {warning.text}
                </p>
              ))}
            </div>
          )}
          <div className="flex flex-col gap-1">
            <h3 lang="tr" className="m-0 text-[17px] font-semibold tracking-[-0.01em]">
              {snapshot.title}
            </h3>
            {snapshot.breadcrumb.length > 0 && (
              <span className="text-[12.5px] text-fg3">{snapshot.breadcrumb.join(' › ')}</span>
            )}
            {!file && (snapshot.authority || sourceSubtitle(snapshot, m)) && (
              <span className="font-mono text-[11.5px] text-fg3">
                {[snapshot.authority, snapshot.decision_metadata.chamber, sourceSubtitle(snapshot, m)].filter(Boolean).join(' · ')}
              </span>
            )}
          </div>
          {snapshot.redacted ? (
            <p className="m-0 rounded-[10px] border border-dashed border-line-strong px-4 py-3.5 text-[13px] leading-normal text-fg3">
              {t.redacted}
            </p>
          ) : (
            <blockquote lang="tr" className="m-0 max-h-[360px] overflow-y-auto whitespace-pre-line rounded-[10px] bg-muted px-4 py-3.5 text-[13.5px] leading-[1.65] text-fg2">
              {snapshot.exact_passage}
            </blockquote>
          )}
          {!file && !web && snapshot.provision_changes && snapshot.provision_changes.length > 0 && (
            <ProvisionHistory changes={snapshot.provision_changes} title={t.history} />
          )}
          {!file && !web && snapshot.cited_provision_changes && snapshot.cited_provision_changes.length > 0 && (
            <ProvisionHistory
              changes={snapshot.cited_provision_changes}
              title={t.citedHistory}
            />
          )}
          {web && (
            <p className="m-0 text-[12.5px] leading-normal text-fg3">
              {t.webExcerpt(snapshot.retrieved_on ? formatDate(snapshot.retrieved_on, m) : null)}
            </p>
          )}
          <div className="flex flex-col gap-2 rounded-[10px] border border-line px-3.5 py-3">
            <div className="flex items-center gap-2 text-[12.5px]">
              <span className="font-semibold">{t.verification}</span>
              <span className="grow" />
              <span className="text-fg3">{t.statements(claimNumbers)}</span>
              {allPartial ? (
                <span className="rounded-full border border-dashed border-line-strong px-2 py-px text-[11.5px] text-fg2">{t.partly}</span>
              ) : (
                <Badge tone="ok">
                  <Icon name="check" size={12} strokeWidth={2.2} />
                  {t.supports}
                </Badge>
              )}
            </div>
            {selected.claims.map((claim) => (
              <p key={claim.number} className="m-0 text-[12.5px] leading-normal text-fg2">
                <span className="font-medium text-fg">{t.statement(claim.number)}</span>{' '}
                {claim.status === 'partial' ? t.partlyLead : ''}
                {claim.reason ? <span lang="tr">{claim.reason}</span> : t.supportsDefault}
              </p>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {file && snapshot.file_id && !snapshot.redacted && (
              <button
                type="button"
                onClick={() => void openFile()}
                className="flex h-8 items-center gap-1.5 rounded-lg border border-line-strong px-3 text-[13px] font-medium text-fg hover:bg-hover"
              >
                <Icon name="ext" size={14} />
                {snapshot.page_number ? t.openInFile(snapshot.page_number) : t.openFile}
              </button>
            )}
            {snapshot.source_url && (
              <a
                href={snapshot.source_url}
                target="_blank"
                rel="noreferrer"
                className="flex h-8 items-center gap-1.5 rounded-lg border border-line-strong px-3 text-[13px] font-medium text-fg no-underline hover:bg-hover"
              >
                <Icon name="ext" size={14} />
                {web ? t.openPage : t.openSource}
              </a>
            )}
            {!snapshot.redacted && (
              <button
                type="button"
                onClick={() => void copyPassage()}
                className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-fg2 hover:bg-hover hover:text-fg"
              >
                <Icon name={copied ? 'check' : 'copy'} size={14} />
                {copied ? m.common.copied : t.copyPassage}
              </button>
            )}
            <span className="grow" />
            {snapshot.corpus_version && (
              <span className="font-mono text-[11px] text-fg3" title={t.sourceVersion}>
                {snapshot.corpus_version}
              </span>
            )}
          </div>
          {openError && <p className="m-0 text-[12.5px] text-err">{openError}</p>}
        </section>

        {others.length > 0 && (
          <section className="flex flex-col gap-0.5 border-t border-line pt-3.5">
            <h3 className="m-0 mb-1.5 text-[12.5px] font-medium text-fg3">{t.others}</h3>
            {others.map((source) => {
              const isDoctrine = source.channel === 'doctrine';
              const isFile = source.channel === 'file';
              const isWeb = source.channel === 'web';
              const partial = source.claims.every((claim) => claim.status === 'partial');
              return (
                <button
                  key={source.sourceId}
                  type="button"
                  onClick={() => onSelect(source.sourceId)}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-[7px] text-left hover:bg-hover"
                >
                  <span
                    className={`flex h-[19px] min-w-[22px] items-center justify-center rounded-[5px] border px-[5px] font-mono text-[11px] font-medium ${
                      isFile
                        ? 'border-file-line bg-file-bg text-file'
                        : isWeb
                          ? 'border-web-line bg-web-bg text-web'
                          : isDoctrine
                            ? 'border-doc-line bg-doc-bg text-doc'
                            : partial
                              ? 'border-dashed border-accent text-accent'
                              : 'border-accent-line bg-accent-bg text-accent'
                    }`}
                  >
                    {source.label}
                  </span>
                  <span className="flex min-w-0 grow flex-col">
                    <span lang="tr" className="truncate text-[13px] font-medium">
                      {source.snapshot.title}
                    </span>
                    <span className="truncate text-xs text-fg3">
                      {isDoctrine ? t.doctrine : sourceSubtitle(source.snapshot, m) || sourceKind(source.snapshot, source.channel, m)}
                    </span>
                  </span>
                  {partial && !isDoctrine && !isFile && !isWeb && (
                    <span className="shrink-0 rounded-full border border-dashed border-line-strong px-[7px] py-px text-[11.5px] text-fg2">{t.partlyShort}</span>
                  )}
                </button>
              );
            })}
          </section>
        )}

        <CitationLegend />
      </div>
    </div>
  );
}

/** What the chips' frames, dots and colours mean, at the foot of the panel. */
function CitationLegend() {
  const { m } = useI18n();
  const t = m.panel;
  const chip = 'flex h-[19px] min-w-[22px] shrink-0 items-center justify-center gap-[3px] rounded-[5px] border px-[5px] font-mono text-[11px] font-medium';
  const rows: [ReactNode, string][] = [
    [<span key="ok" className={`${chip} border-accent-line bg-accent-bg text-accent`}>1</span>, t.legendSupports],
    [<span key="partial" className={`${chip} border-dashed border-accent text-accent`}>1</span>, t.legendPartial],
    [
      <span key="changed" className={`${chip} border-accent-line bg-accent-bg text-accent`}>
        1<span className="size-[5px] rounded-full bg-err" />
      </span>,
      t.legendChanged,
    ],
  ];
  return (
    <section aria-labelledby="citation-legend" className="flex flex-col gap-2 border-t border-line pt-3.5">
      <h3 id="citation-legend" className="m-0 text-[12.5px] font-medium text-fg3">
        {t.legend}
      </h3>
      {rows.map(([sample, text]) => (
        <p key={text} className="m-0 flex items-start gap-2.5 text-[12.5px] leading-normal text-fg2">
          {sample}
          <span>{text}</span>
        </p>
      ))}
      <p className="m-0 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-[12.5px] text-fg2">
        <span className={`${chip} border-accent-line bg-accent-bg text-accent`}>1</span> {t.legendChannels.primary}
        <span className={`${chip} border-doc-line bg-doc-bg text-doc`}>D1</span> {t.legendChannels.doctrine}
        <span className={`${chip} border-file-line bg-file-bg text-file`}>F1</span> {t.legendChannels.file}
        <span className={`${chip} border-web-line bg-web-bg text-web`}>W1</span> {t.legendChannels.web}
      </p>
    </section>
  );
}
