'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { LogoMark } from '@/components/brand';
import { Icon } from '@/components/icons';
import { AuthGate } from './auth';
import { ConversationsProvider } from './conversations';
import { Sidebar } from './sidebar';

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AuthGate>
      <ConversationsProvider>
        <Frame>{children}</Frame>
      </ConversationsProvider>
    </AuthGate>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        router.push('/sohbet');
      }
      if (event.key === 'Escape') setDrawerOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [router]);

  return (
    <div className="flex h-dvh overflow-hidden bg-bg">
      <div className="hidden lg:flex">
        <Sidebar />
      </div>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menü">
          <button
            type="button"
            aria-label="Menüyü kapat"
            className="absolute inset-0 bg-[var(--scrim)]"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="relative h-full w-[308px] max-w-[85vw] shadow-lg">
            <Sidebar onNavigate={() => setDrawerOpen(false)} onClose={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 grow flex-col">
        <div className="flex h-14 shrink-0 items-center gap-1 border-b border-line px-1.5 lg:hidden">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Menüyü aç"
            className="flex size-11 items-center justify-center rounded-[10px] text-fg hover:bg-hover"
          >
            <Icon name="menu" size={20} />
          </button>
          <Link href="/sohbet" className="flex grow items-center gap-2 text-fg no-underline" aria-label="Yeni sohbet">
            <LogoMark size={22} />
            <span className="text-[15px] font-semibold">BekenAI</span>
          </Link>
          <Link
            href="/sohbet"
            aria-label="Yeni sohbet"
            className="flex size-11 items-center justify-center rounded-[10px] text-fg hover:bg-hover"
          >
            <Icon name="edit" size={20} />
          </Link>
        </div>
        <div className="min-h-0 grow">{children}</div>
      </div>
    </div>
  );
}
