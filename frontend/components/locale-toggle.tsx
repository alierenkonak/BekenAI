'use client';

import { useChangeLocale, useI18n } from '@/lib/i18n/client';

// Written in the language it switches to, so a reader of that language can find it.
const SWITCH = {
  tr: { to: 'en', short: 'EN', label: 'Switch to English' },
  en: { to: 'tr', short: 'TR', label: 'Türkçeye geç' },
} as const;

const VARIANTS = {
  outline: 'h-8 min-w-8 border border-line bg-surface text-fg2 hover:bg-hover hover:text-fg',
  // Matches the borderless icon buttons of the sidebar header.
  ghost: 'size-8 text-fg3 hover:bg-hover hover:text-fg',
} as const;

export function LocaleToggle({ variant = 'outline', className = '' }: { variant?: keyof typeof VARIANTS; className?: string }) {
  const { locale } = useI18n();
  const { change, pending } = useChangeLocale();
  const target = SWITCH[locale];
  return (
    <button
      type="button"
      onClick={() => change(target.to)}
      disabled={pending}
      aria-label={target.label}
      title={target.label}
      lang={target.to}
      className={`flex shrink-0 items-center justify-center rounded-lg px-1.5 font-mono text-[11.5px] font-semibold transition-colors disabled:opacity-60 ${VARIANTS[variant]} ${className}`}
    >
      {target.short}
    </button>
  );
}
