'use client';

import { useRouter } from 'next/navigation';
import { createContext, useCallback, useContext, useTransition, type ReactNode } from 'react';
import { DEFAULT_LOCALE, LOCALE_COOKIE, MESSAGES, type Locale, type Messages } from './index';

const LocaleContext = createContext<Locale>(DEFAULT_LOCALE);

/** Set by the root layout from the cookie, so the server and the browser render the same language. */
export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

export function useI18n(): { locale: Locale; m: Messages } {
  const locale = useContext(LocaleContext);
  return { locale, m: MESSAGES[locale] };
}

/**
 * Switches the interface language: the cookie is written and the page is rendered again on the
 * server, so server-rendered sections change together with the rest.
 */
export function useChangeLocale(): { change: (locale: Locale) => void; pending: boolean } {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const change = useCallback(
    (locale: Locale) => {
      document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`;
      document.documentElement.lang = locale;
      startTransition(() => router.refresh());
    },
    [router],
  );
  return { change, pending };
}
