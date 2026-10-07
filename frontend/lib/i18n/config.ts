export const LOCALES = ['tr', 'en'] as const;
export type Locale = (typeof LOCALES)[number];

/** The first visit is in Turkish; the choice is kept in a cookie so the server renders it too. */
export const DEFAULT_LOCALE: Locale = 'tr';
export const LOCALE_COOKIE = 'bekenai-locale';

export function isLocale(value: unknown): value is Locale {
  return value === 'tr' || value === 'en';
}
