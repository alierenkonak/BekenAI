'use client';

import { useCallback, useState, type KeyboardEvent, type PointerEvent } from 'react';

type Bounds = { initial: number; min: number; max: number };

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(Math.round(value), min), max);

function storedWidth(key: string, { initial, min, max }: Bounds): number {
  if (typeof window === 'undefined') return initial;
  try {
    const stored = Number(window.localStorage.getItem(key));
    return stored ? clamp(stored, min, max) : initial;
  } catch {
    return initial; // Storage may be unavailable; the panel keeps its default width.
  }
}

/**
 * A panel width the user can drag, remembered in this browser. The app's panels render only
 * after sign-in, in the browser, so the stored width can be read on the first render.
 */
export function useStoredWidth(key: string, bounds: Bounds) {
  const { initial, min, max } = bounds;
  const [width, setWidth] = useState(() => storedWidth(key, bounds));

  const change = useCallback(
    (value: number) => {
      const next = clamp(value, min, max);
      setWidth(next);
      try {
        window.localStorage.setItem(key, String(next));
      } catch {
        // Not remembered, but the panel still resizes.
      }
    },
    [key, min, max],
  );

  return { width, change, reset: useCallback(() => change(initial), [change, initial]) };
}

/**
 * The drag handle on a panel's edge. `edge` is the side it sits on: a left panel grows when its
 * right edge moves right, a right panel when its left edge moves left. Arrow keys resize by 16 px
 * and a double click restores the default width.
 */
export function ResizeHandle({
  edge,
  width,
  min,
  max,
  onChange,
  onReset,
  label,
}: {
  edge: 'left' | 'right';
  width: number;
  min: number;
  max: number;
  onChange: (width: number) => void;
  onReset: () => void;
  label: string;
}) {
  const direction = edge === 'right' ? 1 : -1;

  const startDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget;
    const startX = event.clientX;
    const startWidth = width;
    handle.setPointerCapture(event.pointerId);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    const move = (moveEvent: globalThis.PointerEvent) => onChange(startWidth + (moveEvent.clientX - startX) * direction);
    const stop = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', stop);
      handle.removeEventListener('pointercancel', stop);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', stop);
    handle.addEventListener('pointercancel', stop);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    onChange(width + (event.key === 'ArrowRight' ? 16 : -16) * direction);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      title="Sürükleyerek boyutlandırın; çift tıklayınca varsayılana döner"
      onPointerDown={startDrag}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className={`group absolute inset-y-0 z-20 w-2.5 cursor-col-resize touch-none outline-none ${edge === 'right' ? '-right-[5px]' : '-left-[5px]'}`}
    >
      <span className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full transition-colors group-hover:bg-accent group-focus-visible:bg-accent group-active:bg-accent" />
    </div>
  );
}
