'use client';

import { usePathname, useRouter } from 'next/navigation';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { describeError } from '@/lib/format';
import { useI18n } from '@/lib/i18n/client';
import type { Conversation } from '@/lib/types';

type ConversationsValue = {
  /** Chats pinned to the top of the sidebar, newest pin first. */
  pinned: Conversation[] | null;
  /** Every other chat, for the dated history. */
  conversations: Conversation[] | null;
  refresh: () => void;
  togglePin: (conversation: Conversation) => Promise<Conversation | null>;
  rename: (conversation: Conversation, title: string) => Promise<Conversation | null>;
  /** Asks first; resolves true once the chat is gone. */
  remove: (conversation: Conversation) => Promise<boolean>;
};

const noop = async () => null;
const ConversationsContext = createContext<ConversationsValue>({
  pinned: null,
  conversations: null,
  refresh: () => {},
  togglePin: noop,
  rename: noop,
  remove: async () => false,
});

export function useConversations(): ConversationsValue {
  return useContext(ConversationsContext);
}

/**
 * Sidebar history and the actions on a chat (pin, rename, delete), shared by the sidebar and
 * the case page. Pages call `refresh()` after creating a chat or sending a question.
 */
export function ConversationsProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { m } = useI18n();
  const [pinned, setPinned] = useState<Conversation[] | null>(null);
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [version, setVersion] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([api.listConversations({ limit: 50, pinned: true }), api.listConversations({ limit: 50, pinned: false })])
      .then(([pinnedPage, otherPage]) => {
        if (!active) return;
        // Filtered here as well, so a server without pins shows one plain history.
        setPinned(
          pinnedPage.items
            .filter((item) => item.pinned_at)
            .sort((a, b) => String(b.pinned_at).localeCompare(String(a.pinned_at))),
        );
        setConversations(otherPage.items.filter((item) => !item.pinned_at));
      })
      .catch(() => {
        if (!active) return;
        setPinned((current) => current ?? []);
        setConversations((current) => current ?? []);
      });
    return () => {
      active = false;
    };
  }, [version]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  const togglePin = useCallback(
    async (conversation: Conversation) => {
      try {
        const updated = await api.updateConversation(conversation.id, { pinned: !conversation.pinned_at });
        refresh();
        return updated;
      } catch (error) {
        setNotice(describeError(error, m));
        return null;
      }
    },
    [m, refresh],
  );

  const rename = useCallback(
    async (conversation: Conversation, title: string) => {
      const next = title.replace(/\s+/g, ' ').trim().slice(0, 160);
      if (!next || next === conversation.title) return conversation;
      try {
        const updated = await api.updateConversation(conversation.id, { title: next });
        refresh();
        return updated;
      } catch (error) {
        setNotice(describeError(error, m));
        return null;
      }
    },
    [m, refresh],
  );

  const remove = useCallback(
    async (conversation: Conversation) => {
      if (!window.confirm(m.chatMenu.confirmDelete(conversation.title))) return false;
      try {
        await api.deleteConversation(conversation.id);
        refresh();
        if (pathname === `/sohbet/${conversation.id}`) router.push('/sohbet');
        return true;
      } catch (error) {
        setNotice(describeError(error, m));
        return false;
      }
    },
    [m, pathname, refresh, router],
  );

  const value = useMemo(
    () => ({ pinned, conversations, refresh, togglePin, rename, remove }),
    [pinned, conversations, refresh, togglePin, rename, remove],
  );

  return (
    <ConversationsContext.Provider value={value}>
      {children}
      {notice && (
        <p
          role="alert"
          className="fixed bottom-5 left-1/2 z-50 m-0 -translate-x-1/2 rounded-[10px] border border-err-line bg-surface px-3.5 py-2.5 text-[13px] text-err shadow-lg"
        >
          {notice}
        </p>
      )}
    </ConversationsContext.Provider>
  );
}
