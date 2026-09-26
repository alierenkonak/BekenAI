'use client';

import { useEffect, useState, useSyncExternalStore, type RefObject } from 'react';

function subscribeReducedMotion(onChange: () => void): () => void {
  const query = window.matchMedia('(prefers-reduced-motion: reduce)');
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    () => false,
  );
}

/** True while the element is at least partly on screen; animations pause otherwise. */
export function useInView(ref: RefObject<Element | null>): boolean {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), {
      rootMargin: '120px',
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return visible;
}

/** Wall-clock milliseconds, refreshed every `periodMs` (0 until the first tick). */
export function useNow(periodMs = 1000): number {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = window.setTimeout(tick, 0);
    const id = window.setInterval(tick, periodMs);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [periodMs]);
  return now;
}
