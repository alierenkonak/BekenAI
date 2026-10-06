'use client';

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import { createPortal } from 'react-dom';
import { Icon, type IconName } from '@/components/icons';

type Placement = 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end';

const GAP = 6;
const MARGIN = 8;

/**
 * A panel anchored to its trigger. It renders into <body>, so a scrolling list (the sidebar's
 * history) cannot clip it, flips above the trigger when there is no room below, and closes on
 * a click outside or Escape (returning focus to the trigger).
 */
export function Popover({
  open,
  onClose,
  anchorRef,
  placement = 'bottom-start',
  className = '',
  children,
  ...aria
}: {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<HTMLElement | null>;
  placement?: Placement;
  className?: string;
  children: ReactNode;
  id?: string;
  role?: string;
  'aria-label'?: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<CSSProperties>({ visibility: 'hidden' });

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const anchor = anchorRef.current?.getBoundingClientRect();
      const panel = panelRef.current;
      if (!anchor || !panel) return;
      const { offsetWidth: width, offsetHeight: height } = panel;
      const above = anchor.top - height - GAP;
      const below = anchor.bottom + GAP;
      let top = placement.startsWith('top') ? above : below;
      if (top === below && below + height > window.innerHeight - MARGIN && above >= MARGIN) top = above;
      if (top === above && above < MARGIN) top = below;
      const left = placement.endsWith('end') ? anchor.right - width : anchor.left;
      setStyle({ top, left: Math.min(Math.max(MARGIN, left), window.innerWidth - width - MARGIN), visibility: 'visible' });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, anchorRef, placement]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      onClose();
      anchorRef.current?.focus();
    };
    document.addEventListener('pointerdown', onPointer, true);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer, true);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose, anchorRef]);

  if (!open) return null;
  return createPortal(
    <div
      ref={panelRef}
      {...aria}
      style={style}
      className={`fixed z-50 rounded-xl border border-line bg-surface p-1 shadow-lg ${className}`}
    >
      {children}
    </div>,
    document.body,
  );
}

/** Moves focus between the panel's items with the arrow keys, Home and End. */
export function moveFocus(event: KeyboardEvent<HTMLElement>, selector: string) {
  const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(selector));
  const index = items.indexOf(document.activeElement as HTMLElement);
  const next =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? items.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
  items[next]?.focus();
}

export type MenuItem = { label: string; icon: IconName; onSelect: () => void; danger?: boolean };

/** An action menu; the first item takes focus when it opens. */
export function Menu({
  open,
  onClose,
  anchorRef,
  items,
  label,
  placement = 'bottom-end',
}: {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<HTMLElement | null>;
  items: MenuItem[];
  label: string;
  placement?: Placement;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) window.requestAnimationFrame(() => listRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus());
  }, [open]);

  return (
    <Popover open={open} onClose={onClose} anchorRef={anchorRef} placement={placement} className="min-w-[184px]">
      <div ref={listRef} role="menu" aria-label={label} onKeyDown={(event) => moveFocus(event, '[role="menuitem"]')} className="flex flex-col">
        {items.map((item) => (
          <button
            key={item.label}
            type="button"
            role="menuitem"
            onClick={() => {
              onClose();
              item.onSelect();
            }}
            className={`flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] outline-none hover:bg-hover focus-visible:bg-hover ${
              item.danger ? 'text-err' : 'text-fg'
            }`}
          >
            <Icon name={item.icon} size={15} />
            {item.label}
          </button>
        ))}
      </div>
    </Popover>
  );
}
