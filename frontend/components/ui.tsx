import type { ReactNode } from 'react';

export function DoctrineSwitch({
  checked,
  onChange,
  label = 'Doktrin kaynakları',
  compact = false,
  disabled = false,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label?: string;
  compact?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`flex items-center gap-2 rounded-lg border px-2.5 text-[13px] transition-colors disabled:opacity-50 ${
        compact ? 'h-[30px]' : 'h-8'
      } ${checked ? 'border-doc-line bg-doc-bg font-medium text-doc' : 'border-line bg-transparent text-fg2 hover:bg-hover'}`}
    >
      <span
        className={`flex h-4 w-7 shrink-0 rounded-full p-0.5 transition-colors ${checked ? 'justify-end bg-doc' : 'justify-start bg-line-strong'}`}
      >
        <span className="size-3 rounded-full bg-surface" />
      </span>
      {label}
    </button>
  );
}

export type ChipTone = 'primary' | 'selected' | 'partial' | 'doctrine' | 'doctrineSelected';

const CHIP_TONES: Record<ChipTone, string> = {
  primary: 'border-accent-line bg-accent-bg text-accent',
  selected: 'border-accent bg-accent text-inv-fg',
  partial: 'border-dashed border-accent bg-transparent text-accent',
  doctrine: 'border-doc-line bg-doc-bg text-doc',
  doctrineSelected: 'border-doc bg-doc text-inv-fg',
};

export function CitationChip({
  label,
  tone,
  onClick,
  ariaLabel,
}: {
  label: string;
  tone: ChipTone;
  onClick?: () => void;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className={`ml-1 inline-flex h-[19px] min-w-5 items-center justify-center rounded-[5px] border px-[5px] align-[1px] font-mono text-[11px] font-medium transition-colors ${CHIP_TONES[tone]}`}
    >
      {label}
    </button>
  );
}

export function Badge({ tone, children }: { tone: 'ok' | 'accent' | 'neutral' | 'err' | 'doc'; children: ReactNode }) {
  const tones = {
    ok: 'bg-ok-bg text-ok',
    accent: 'bg-accent-bg text-accent',
    neutral: 'bg-muted text-fg2',
    err: 'bg-err-bg text-err',
    doc: 'bg-doc-bg text-doc',
  };
  return (
    <span className={`inline-flex h-[22px] items-center gap-1.5 rounded-full px-2 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <span className="text-xs font-medium tracking-[0.18em] text-fg3">{children}</span>;
}

/** Visually hidden label text for screen readers. */
export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}
