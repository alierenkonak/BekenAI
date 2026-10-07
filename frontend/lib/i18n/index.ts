import type { Locale } from './config';
import { en } from './en';
import { tr, type Messages } from './tr';

export * from './config';
export type { Messages };

export const MESSAGES: Record<Locale, Messages> = { tr, en };
