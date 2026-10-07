'use client';

import { useI18n } from '@/lib/i18n/client';
import { setTheme, useTheme } from '@/lib/theme';
import { Icon } from './icons';

export function ThemeToggle({ className = '' }: { className?: string }) {
  const theme = useTheme();
  const { m } = useI18n();
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={next === 'dark' ? m.theme.toDark : m.theme.toLight}
      title={next === 'dark' ? m.theme.dark : m.theme.light}
      className={`flex size-8 items-center justify-center rounded-lg border border-line bg-surface text-fg2 transition-colors hover:bg-hover hover:text-fg ${className}`}
    >
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
    </button>
  );
}
