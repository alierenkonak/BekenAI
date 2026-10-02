'use client';

import type { ReactNode } from 'react';
import { Icon, Spinner } from '@/components/icons';
import { DeepResearchSwitch, WebSearchSwitch } from '@/components/ui';
import { CHAT_MESSAGE_MAX } from '@/lib/config';
import { DEEP_RESEARCH_HINT } from '@/lib/research';
import { WEB_SEARCH_HINT } from '@/lib/web-search';

export function Composer({
  value,
  onChange,
  onSubmit,
  webSearch,
  deepResearch,
  busy = false,
  variant,
  placeholder,
  extra,
  autoFocus = false,
  locked = null,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** Present only when the server can search the web. */
  webSearch?: { checked: boolean; onChange: (value: boolean) => void };
  deepResearch?: { checked: boolean; onChange: (value: boolean) => void };
  busy?: boolean;
  variant: 'hero' | 'compact';
  placeholder: string;
  extra?: ReactNode;
  autoFocus?: boolean;
  /** Why sending is paused (files still processing); typing stays possible. */
  locked?: string | null;
}) {
  const length = value.trim().length;
  const canSend = !busy && !locked && length >= 3 && value.length <= CHAT_MESSAGE_MAX;
  const nearLimit = value.length > CHAT_MESSAGE_MAX * 0.9;

  const submit = () => {
    if (canSend) onSubmit();
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className={`relative flex flex-col border border-line-strong bg-surface shadow-soft ${variant === 'hero' ? 'rounded-2xl' : 'rounded-[14px]'}`}
    >
      {locked && (
        <p role="status" className="m-0 flex items-center gap-2 border-b border-line px-4 py-2.5 text-[12.5px] text-fg2">
          <Spinner size={13} className="shrink-0 text-file" />
          <span className="min-w-0">{locked}</span>
        </p>
      )}
      <label htmlFor={`composer-${variant}`} className="sr-only">
        Sorunuz
      </label>
      <textarea
        id={`composer-${variant}`}
        value={value}
        autoFocus={autoFocus}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        rows={variant === 'hero' ? 3 : 1}
        maxLength={CHAT_MESSAGE_MAX + 200}
        placeholder={placeholder}
        className={`field-sizing-content max-h-60 resize-none border-0 bg-transparent text-fg outline-none placeholder:text-fg3 ${
          variant === 'hero' ? 'min-h-[88px] px-[18px] pb-1.5 pt-[18px] text-[15px] leading-normal' : 'min-h-11 px-4 pb-1 pt-3 text-[14.5px] leading-normal'
        }`}
      />
      <div className="flex flex-wrap items-center gap-2 px-3 pb-3 pt-2">
        {variant === 'hero' && (
          <span className="flex h-8 items-center gap-1.5 rounded-lg border border-line bg-muted px-2.5 text-[13px] font-medium">
            <Icon name="scale" size={15} />
            İş Hukuku
          </span>
        )}
        {webSearch && (
          <WebSearchSwitch
            checked={webSearch.checked}
            onChange={webSearch.onChange}
            compact={variant === 'compact'}
            label={variant === 'hero' ? 'Web araması' : 'Web'}
            hintId={`web-search-hint-${variant}`}
            hint={WEB_SEARCH_HINT}
          />
        )}
        {deepResearch && (
          <DeepResearchSwitch
            checked={deepResearch.checked}
            onChange={deepResearch.onChange}
            compact={variant === 'compact'}
            label={variant === 'hero' ? 'Derin araştırma' : 'Derin'}
            hintId={`deep-research-hint-${variant}`}
            hint={DEEP_RESEARCH_HINT}
          />
        )}
        {extra}
        {/* Counter and send button stay together on the right, also when the row wraps. */}
        <span className="ml-auto flex items-center gap-2">
          <span className={`font-mono text-[11.5px] ${nearLimit ? 'text-err' : 'text-fg3'}`} aria-live="polite">
            {value.length} / {CHAT_MESSAGE_MAX}
          </span>
          <button
            type="submit"
            disabled={!canSend}
            aria-label="Soruyu gönder"
            className="flex size-[34px] items-center justify-center rounded-[10px] bg-inv text-inv-fg transition-opacity disabled:opacity-35"
          >
            {busy ? <Spinner /> : <Icon name="arrowUp" size={17} strokeWidth={2} />}
          </button>
        </span>
      </div>
    </form>
  );
}
