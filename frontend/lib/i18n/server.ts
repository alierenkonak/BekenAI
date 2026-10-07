import { cookies } from 'next/headers';
import { DEFAULT_LOCALE, LOCALE_COOKIE, MESSAGES, isLocale, type Locale, type Messages } from './index';

/** The visitor's interface language, from the cookie the language switch sets. */
export async function getLocale(): Promise<Locale> {
  const value = (await cookies()).get(LOCALE_COOKIE)?.value;
  return isLocale(value) ? value : DEFAULT_LOCALE;
}

export async function getI18n(): Promise<{ locale: Locale; m: Messages }> {
  const locale = await getLocale();
  return { locale, m: MESSAGES[locale] };
}
