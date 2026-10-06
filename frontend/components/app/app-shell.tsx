'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { Logo } from '@/components/brand';
import { Icon } from '@/components/icons';
import { AuthGate } from './auth';
import { ConversationsProvider } from './conversations';
import { ResizeHandle, useStoredFlag, useStoredWidth } from './resize-handle';
import { Sidebar } from './sidebar';

const SIDEBAR = { initial: 264, min: 220, max: 420 };

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
  const sidebar = useStoredWidth('bekenai-sidebar-width', SIDEBAR);
  const [sidebarClosed, setSidebarClosed] = useStoredFlag('bekenai-sidebar-closed');

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
      {sidebarClosed ? (
        // Closed: a thin strip keeps the way back and a new chat one click away.
        <div className="hidden w-[52px] shrink-0 flex-col items-center gap-1.5 border-r border-line bg-side py-3 lg:flex">
          <button
            type="button"
            onClick={() => setSidebarClosed(false)}
            aria-label="Kenar çubuğunu aç"
            title="Kenar çubuğunu aç"
            className="flex size-9 items-center justify-center rounded-lg text-fg2 hover:bg-hover hover:text-fg"
          >
            <Icon name="sidebar" size={18} />
          </button>
          <Link
            href="/sohbet"
            aria-label="Yeni sohbet"
            title="Yeni sohbet"
            className="flex size-9 items-center justify-center rounded-lg text-fg2 hover:bg-hover hover:text-fg"
          >
            <Icon name="edit" size={17} />
          </Link>
        </div>
      ) : (
        <div className="relative hidden shrink-0 lg:flex" style={{ width: sidebar.width }}>
          <Sidebar onCollapse={() => setSidebarClosed(true)} />
          <ResizeHandle
            edge="right"
            width={sidebar.width}
            min={SIDEBAR.min}
            max={SIDEBAR.max}
            onChange={sidebar.change}
            // Dragged well past its narrowest width, the sidebar closes.
            collapseBelow={SIDEBAR.min - 64}
            onCollapse={() => setSidebarClosed(true)}
            onReset={sidebar.reset}
            label="Kenar çubuğunun genişliği"
          />
        </div>
      )}

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
          <Logo href="/sohbet" size={28} className="grow" />
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
