'use client';

import { useRef, useState } from 'react';
import { Icon } from '@/components/icons';
import { useI18n } from '@/lib/i18n/client';
import type { Conversation } from '@/lib/types';
import { useConversations } from './conversations';
import { Menu } from './popover';

/**
 * The "…" button of a chat row: pin, rename, delete. It shows on hover, for the open chat and
 * on keyboard focus; touch screens, which cannot hover, always show it (globals.css).
 */
export function ConversationMenuButton({
  conversation,
  onRename,
  onChanged,
}: {
  conversation: Conversation;
  onRename: () => void;
  /** Called after a pin or delete succeeds, for lists the sidebar does not own. */
  onChanged?: () => void;
}) {
  const { togglePin, remove } = useConversations();
  const { m } = useI18n();
  const t = m.chatMenu;
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={t.options(conversation.title)}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="hover-reveal flex size-7 shrink-0 items-center justify-center rounded-md text-fg3 hover:bg-line hover:text-fg"
      >
        <Icon name="more" size={16} />
      </button>
      <Menu
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={triggerRef}
        label={t.label}
        items={[
          {
            label: conversation.pinned_at ? t.unpin : t.pin,
            icon: 'pin',
            onSelect: () => void togglePin(conversation).then((updated) => updated && onChanged?.()),
          },
          { label: t.rename, icon: 'edit', onSelect: onRename },
          {
            label: t.delete,
            icon: 'trash',
            danger: true,
            onSelect: () => void remove(conversation).then((removed) => removed && onChanged?.()),
          },
        ]}
      />
    </>
  );
}

/** Edits a chat's title in place: Enter or leaving the field saves, Escape cancels. */
export function RenameField({
  conversation,
  onDone,
  className = '',
}: {
  conversation: Conversation;
  onDone: (updated: Conversation | null) => void;
  className?: string;
}) {
  const { rename } = useConversations();
  const { m } = useI18n();
  const [value, setValue] = useState(conversation.title);
  const settled = useRef(false);

  const finish = async (save: boolean) => {
    if (settled.current) return;
    settled.current = true;
    onDone(save ? await rename(conversation, value) : null);
  };

  return (
    <input
      autoFocus
      aria-label={m.chatMenu.newName}
      value={value}
      maxLength={160}
      onFocus={(event) => event.currentTarget.select()}
      onChange={(event) => setValue(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          void finish(true);
        }
        if (event.key === 'Escape') {
          event.preventDefault();
          void finish(false);
        }
      }}
      onBlur={() => void finish(true)}
      className={`min-w-0 rounded-md border border-accent bg-surface px-2 text-fg outline-none ${className}`}
    />
  );
}
