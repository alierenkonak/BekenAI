'use client';

import { useState } from 'react';

const TICK = 16;
const LENGTHS = [40, 30, 22, 16, 12];

/**
 * One tick per question. Hovering magnifies the tick under the pointer and its
 * neighbours (dock-style), previews the question, and a click jumps to it.
 */
export function PromptRail({
  prompts,
  activeIndex,
  onJump,
}: {
  prompts: { text: string; time: string }[];
  activeIndex: number;
  onJump: (index: number) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const preview = hover === null ? null : prompts[hover];

  return (
    <nav
      aria-label="Sohbet haritası"
      onMouseLeave={() => setHover(null)}
      className="absolute left-1.5 top-1/2 z-10 hidden w-11 -translate-y-1/2 flex-col lg:flex"
      style={{ height: prompts.length * TICK }}
    >
      {prompts.map((prompt, index) => {
        const distance = hover === null ? Infinity : Math.abs(index - hover);
        const active = index === activeIndex;
        let length = distance < LENGTHS.length ? LENGTHS[distance] : active ? 18 : 10;
        if (active && length < 18) length = 18;
        const color = distance === 0 || active ? 'var(--fg)' : distance <= 2 ? 'var(--fg3)' : 'var(--tick)';
        return (
          <button
            key={index}
            type="button"
            aria-label={`${index + 1}. soru: ${prompt.text}`}
            aria-current={active ? 'true' : undefined}
            onMouseEnter={() => setHover(index)}
            onFocus={() => setHover(index)}
            onBlur={() => setHover(null)}
            onClick={() => onJump(index)}
            className="flex w-11 shrink-0 items-center pl-1"
            style={{ height: TICK }}
          >
            <span
              className="block h-0.5 rounded-sm transition-[width,background-color] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]"
              style={{ width: length, background: color }}
            />
          </button>
        );
      })}
      {preview && hover !== null && (
        <div
          role="tooltip"
          className="pointer-events-none absolute left-[54px] flex w-[300px] flex-col gap-1.5 rounded-[14px] border border-line bg-surface px-3.5 py-3 shadow-soft transition-[top] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]"
          style={{ top: Math.max(-24, hover * TICK - 22) }}
        >
          <span className="font-mono text-[11px] text-fg3">
            Soru {hover + 1} · {preview.time}
          </span>
          <span className="text-[13.5px] leading-normal text-fg">
            {preview.text.length > 140 ? `${preview.text.slice(0, 137)}…` : preview.text}
          </span>
        </div>
      )}
    </nav>
  );
}
