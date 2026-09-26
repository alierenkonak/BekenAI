'use client';

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import type { Conversation } from '@/lib/types';

type ConversationsValue = {
  conversations: Conversation[] | null;
  refresh: () => void;
};

const ConversationsContext = createContext<ConversationsValue>({ conversations: null, refresh: () => {} });

export function useConversations(): ConversationsValue {
  return useContext(ConversationsContext);
}

/** Sidebar history. Pages call `refresh()` after creating, renaming or deleting a chat. */
export function ConversationsProvider({ children }: { children: ReactNode }) {
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    api
      .listConversations({ limit: 50 })
      .then((page) => {
        if (active) setConversations(page.items);
      })
      .catch(() => {
        if (active) setConversations((current) => current ?? []);
      });
    return () => {
      active = false;
    };
  }, [version]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  return <ConversationsContext.Provider value={{ conversations, refresh }}>{children}</ConversationsContext.Provider>;
}
