import type { ReactNode } from 'react';

const SWITCH_TONES = {
  web: { on: 'border-web-line bg-web-bg font-medium text-web', track: 'bg-web' },
  accent: { on: 'border-accent-line bg-accent-bg font-medium text-accent', track: 'bg-accent' },
} as const;

function Switch({
  checked,
  onChange,
  label,
  tone,
  compact = false,
  disabled = false,
  describedBy,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  tone: keyof typeof SWITCH_TONES;
  compact?: boolean;
  disabled?: boolean;
  describedBy?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-describedby={describedBy}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`flex items-center gap-2 rounded-lg border px-2.5 text-[13px] transition-colors disabled:opacity-50 ${
        compact ? 'h-[30px]' : 'h-8'
      } ${checked ? SWITCH_TONES[tone].on : 'border-line bg-transparent text-fg2 hover:bg-hover'}`}
    >
      <span
        className={`flex h-4 w-7 shrink-0 rounded-full p-0.5 transition-colors ${checked ? `justify-end ${SWITCH_TONES[tone].track}` : 'justify-start bg-line-strong'}`}
      >
        <span className="size-3 rounded-full bg-surface" />
      </span>
      {label}
    </button>
  );
}

type HintedSwitchProps = {
  checked: boolean;
  onChange: (value: boolean) => void;
  hintId: string;
  hint: ReactNode;
  label?: string;
  compact?: boolean;
  disabled?: boolean;
};

/**
 * A switch with a hint shown on hover or keyboard focus. The hint is positioned against
 * the nearest positioned ancestor (the composer), so it never spills off a narrow screen.
 */
function HintedSwitch({ hintId, hint, label, tone, ...props }: HintedSwitchProps & { label: string; tone: keyof typeof SWITCH_TONES }) {
  return (
    <span className="group flex">
      <Switch {...props} label={label} tone={tone} describedBy={hintId} />
      <span
        role="tooltip"
        id={hintId}
        className="pointer-events-none invisible absolute bottom-full left-3 z-30 mb-2 w-[min(360px,calc(100%-24px))] rounded-[10px] bg-inv px-3.5 py-2.5 text-[12.5px] font-normal leading-normal text-inv-fg opacity-0 shadow-lg transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        {hint}
      </span>
    </span>
  );
}

export function WebSearchSwitch({ label = 'Web araması', ...props }: HintedSwitchProps) {
  return <HintedSwitch {...props} label={label} tone="web" />;
}

/** Deep research for the next question only; it turns itself off once the question is sent. */
export function DeepResearchSwitch({ label = 'Derin araştırma', ...props }: HintedSwitchProps) {
  return <HintedSwitch {...props} label={label} tone="accent" />;
}

export type ChipTone =
  | 'primary'
  | 'selected'
  | 'partial'
  | 'doctrine'
  | 'doctrineSelected'
  | 'file'
  | 'fileSelected'
  | 'filePartial'
  | 'web'
  | 'webSelected'
  | 'webPartial';

const CHIP_TONES: Record<ChipTone, string> = {
  primary: 'border-accent-line bg-accent-bg text-accent',
  selected: 'border-accent bg-accent text-inv-fg',
  partial: 'border-dashed border-accent bg-transparent text-accent',
  doctrine: 'border-doc-line bg-doc-bg text-doc',
  doctrineSelected: 'border-doc bg-doc text-inv-fg',
  file: 'border-file-line bg-file-bg text-file',
  fileSelected: 'border-file bg-file text-inv-fg',
  filePartial: 'border-dashed border-file bg-transparent text-file',
  web: 'border-web-line bg-web-bg text-web',
  webSelected: 'border-web bg-web text-inv-fg',
  webPartial: 'border-dashed border-web bg-transparent text-web',
};

export function CitationChip({
  label,
  tone,
  onClick,
  ariaLabel,
  flagged = false,
}: {
  label: string;
  tone: ChipTone;
  onClick?: () => void;
  ariaLabel: string;
  /** Marks a source with a Yürürlük kontrolü warning. */
  flagged?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className={`ml-1 inline-flex h-[19px] min-w-5 items-center justify-center gap-[3px] rounded-[5px] border px-[5px] align-[1px] font-mono text-[11px] font-medium transition-colors ${CHIP_TONES[tone]}`}
    >
      {label}
      {flagged && <span aria-hidden className="h-[5px] w-[5px] shrink-0 rounded-full bg-err" />}
    </button>
  );
}

export function Badge({ tone, children }: { tone: 'ok' | 'accent' | 'neutral' | 'err' | 'doc' | 'file' | 'web'; children: ReactNode }) {
  const tones = {
    ok: 'bg-ok-bg text-ok',
    accent: 'bg-accent-bg text-accent',
    neutral: 'bg-muted text-fg2',
    err: 'bg-err-bg text-err',
    doc: 'bg-doc-bg text-doc',
    file: 'bg-file-bg text-file',
    web: 'bg-web-bg text-web',
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
