'use client';

import { useState } from 'react';
import { Icon } from '@/components/icons';
import { Badge } from '@/components/ui';
import { sourceKind, sourceSubtitle, type SourceRef } from '@/lib/answer';

export function SourcePanel({
  selected,
  sources,
  onSelect,
  onClose,
}: {
  selected: SourceRef;
  sources: SourceRef[];
  onSelect: (sourceId: string) => void;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const { snapshot } = selected;
  const doctrine = selected.channel === 'doctrine';
  const file = selected.channel === 'file';
  const tone = file
    ? { solid: 'bg-file', soft: 'bg-file-bg text-file' }
    : doctrine
      ? { solid: 'bg-doc', soft: 'bg-doc-bg text-doc' }
      : { solid: 'bg-accent', soft: 'bg-accent-bg text-accent' };
  const kind = file
    ? `Dosya${snapshot.location_label ? ` · ${snapshot.location_label}` : ''}`
    : doctrine
      ? 'Doktrin · yardımcı kaynak'
      : `Birincil · ${sourceKind(snapshot, selected.channel)}`;
  const allPartial = selected.claims.every((claim) => claim.status === 'partial');
  const claimNumbers = selected.claims.map((claim) => claim.number).join(', ');
  const others = sources.filter((source) => source.sourceId !== selected.sourceId);

  const copyPassage = async () => {
    try {
      const where = [snapshot.location_label, ...snapshot.breadcrumb].filter(Boolean).join(', ');
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
        <h2 className="m-0 text-sm font-semibold">Kaynaklar</h2>
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 text-[11.5px] font-medium text-fg2">
          {sources.length}
        </span>
        <span className="grow" />
        <button
          type="button"
          onClick={onClose}
          aria-label="Kaynak panelini kapat"
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
          </div>
          <div className="flex flex-col gap-1">
            <h3 className="m-0 text-[17px] font-semibold tracking-[-0.01em]">{snapshot.title}</h3>
            {snapshot.breadcrumb.length > 0 && (
              <span className="text-[12.5px] text-fg3">{snapshot.breadcrumb.join(' › ')}</span>
            )}
            {!file && (snapshot.authority || sourceSubtitle(snapshot)) && (
              <span className="font-mono text-[11.5px] text-fg3">
                {[snapshot.authority, snapshot.decision_metadata.chamber, sourceSubtitle(snapshot)].filter(Boolean).join(' · ')}
              </span>
            )}
          </div>
          {snapshot.redacted ? (
            <p className="m-0 rounded-[10px] border border-dashed border-line-strong px-4 py-3.5 text-[13px] leading-normal text-fg3">
              Bu dosya silindiği için pasaj artık gösterilmiyor.
            </p>
          ) : (
            <blockquote className="m-0 max-h-[360px] overflow-y-auto whitespace-pre-line rounded-[10px] bg-muted px-4 py-3.5 text-[13.5px] leading-[1.65] text-fg2">
              {snapshot.exact_passage}
            </blockquote>
          )}
          <div className="flex flex-col gap-2 rounded-[10px] border border-line px-3.5 py-3">
            <div className="flex items-center gap-2 text-[12.5px]">
              <span className="font-semibold">Doğrulama</span>
              <span className="grow" />
              <span className="text-fg3">İddia {claimNumbers}</span>
              {allPartial ? (
                <span className="rounded-full border border-dashed border-line-strong px-2 py-px text-[11.5px] text-fg2">Kısmen destekliyor</span>
              ) : (
                <Badge tone="ok">
                  <Icon name="check" size={12} strokeWidth={2.2} />
                  Destekliyor
                </Badge>
              )}
            </div>
            {selected.claims.map((claim) => (
              <p key={claim.number} className="m-0 text-[12.5px] leading-normal text-fg2">
                <span className="font-medium text-fg">İddia {claim.number}:</span>{' '}
                {claim.status === 'partial' ? 'Kısmen destekliyor. ' : ''}
                {claim.reason || 'Pasaj bu iddiayı destekliyor.'}
              </p>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {snapshot.source_url && (
              <a
                href={snapshot.source_url}
                target="_blank"
                rel="noreferrer"
                className="flex h-8 items-center gap-1.5 rounded-lg border border-line-strong px-3 text-[13px] font-medium text-fg no-underline hover:bg-hover"
              >
                <Icon name="ext" size={14} />
                Kaynağı aç
              </a>
            )}
            {!snapshot.redacted && (
              <button
                type="button"
                onClick={() => void copyPassage()}
                className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-fg2 hover:bg-hover hover:text-fg"
              >
                <Icon name={copied ? 'check' : 'copy'} size={14} />
                {copied ? 'Kopyalandı' : 'Pasajı kopyala'}
              </button>
            )}
            <span className="grow" />
            {snapshot.corpus_version && (
              <span className="font-mono text-[11px] text-fg3" title="Kaynak sürümü">
                {snapshot.corpus_version}
              </span>
            )}
          </div>
        </section>

        {others.length > 0 && (
          <section className="flex flex-col gap-0.5 border-t border-line pt-3.5">
            <h3 className="m-0 mb-1.5 text-[12.5px] font-medium text-fg3">Bu cevaptaki diğer kaynaklar</h3>
            {others.map((source) => {
              const isDoctrine = source.channel === 'doctrine';
              const isFile = source.channel === 'file';
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
                    <span className="truncate text-[13px] font-medium">{source.snapshot.title}</span>
                    <span className="truncate text-xs text-fg3">
                      {isDoctrine ? 'Doktrin' : sourceSubtitle(source.snapshot) || sourceKind(source.snapshot, source.channel)}
                    </span>
                  </span>
                  {partial && !isDoctrine && !isFile && (
                    <span className="shrink-0 rounded-full border border-dashed border-line-strong px-[7px] py-px text-[11.5px] text-fg2">Kısmen</span>
                  )}
                </button>
              );
            })}
          </section>
        )}
      </div>
    </div>
  );
}
