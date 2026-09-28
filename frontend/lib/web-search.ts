'use client';

import { useEffect, useState } from 'react';
import { api } from './api';
import type { ChatCapabilities } from './types';

// Server features do not change while the app is open; ask once, retry after a failure.
let capabilities: Promise<ChatCapabilities> | null = null;
function loadCapabilities(): Promise<ChatCapabilities> {
  capabilities ??= api.chatCapabilities().catch((error) => {
    capabilities = null;
    throw error;
  });
  return capabilities;
}

/** Whether the server can search the web (it needs a search API key). */
export function useWebSearchAvailable(): boolean {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    let active = true;
    loadCapabilities()
      .then((loaded) => {
        if (active) setAvailable(loaded.web_search);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  return available;
}

const PREFIX = 'bekenai-web:';

/** The web search switch stays on for the rest of a chat; a new chat starts with it off. */
export function rememberWebSearch(conversationId: string, on: boolean) {
  try {
    if (on) window.sessionStorage.setItem(PREFIX + conversationId, '1');
    else window.sessionStorage.removeItem(PREFIX + conversationId);
  } catch {
    // Storage may be unavailable (private mode); the switch then resets on reload.
  }
}

export function readWebSearch(conversationId: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.sessionStorage.getItem(PREFIX + conversationId) === '1';
  } catch {
    return false;
  }
}

export const WEB_SEARCH_HINT =
  'Cevap önce her zamanki gibi BekenAI’nin mevzuat, içtihat ve dosya kaynaklarıyla hazırlanır. Ardından aynı soru web’de de aranır; bulunanlar (cevabı destekleyen ya da ondan farklı bilgiler) en alta ayrı ve etiketli bir bölüm olarak eklenir. Web sayfaları resmî kaynak değildir.';
