'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { Logo } from '@/components/brand';
import { Icon, type IconName } from '@/components/icons';
import { ThemeToggle } from '@/components/theme-toggle';
import { historyGroup, initials } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import type { Conversation } from '@/lib/types';
import { useAuth } from './auth';
import { ConversationMenuButton, RenameField } from './conversation-item';
import { useConversations } from './conversations';

const NAV: { href: string; label: string; icon: IconName; match: (path: string) => boolean }[] = [
  { href: '/sohbet', label: 'Sohbetler', icon: 'chat', match: (path) => path.startsWith('/sohbet') },
  { href: '/davalar', label: 'Davalar', icon: 'cases', match: (path) => path.startsWith('/davalar') },
  { href: '/arama', label: 'Kaynak arama', icon: 'search', match: (path) => path.startsWith('/arama') },
];

const GROUP_ORDER = ['Bugün', 'Önceki 7 gün', 'Daha eski'] as const;

export function Sidebar({ onNavigate, onClose }: { onNavigate?: () => void; onClose?: () => void }) {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  const { pinned, conversations } = useConversations();
  const now = useNow(60_000);
  const name =
    (user.user_metadata?.full_name as string | undefined) ||
    (user.user_metadata?.name as string | undefined) ||
    user.email ||
    'Kullanıcı';

  const groups = GROUP_ORDER.map((label) => ({
    label,
    items: now && conversations ? conversations.filter((item) => historyGroup(item.updated_at, now) === label) : [],
  })).filter((group) => group.items.length > 0);

  return (
    <nav aria-label="Ana gezinme" className="flex h-full w-full flex-col gap-4 border-r border-line bg-side p-3">
      <div className="flex h-10 items-center justify-between pl-1.5 pr-1">
        <Logo href="/sohbet" size={30} />
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Menüyü kapat"
            className="flex size-10 items-center justify-center rounded-lg text-fg2 hover:bg-hover"
          >
            <Icon name="x" size={18} />
          </button>
        )}
      </div>

      <Link
        href="/sohbet"
        onClick={onNavigate}
        className="flex h-[38px] items-center gap-2 rounded-[9px] border border-line-strong bg-surface px-3 text-[13.5px] font-medium text-fg no-underline hover:bg-hover"
      >
        <Icon name="plus" strokeWidth={1.9} />
        <span className="grow">Yeni sohbet</span>
      </Link>

      <div className="flex flex-col gap-0.5">
        {NAV.map((item) => {
          const active = item.href === '/sohbet' ? pathname === '/sohbet' || pathname.startsWith('/sohbet/') : item.match(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? 'page' : undefined}
              className={`flex h-[34px] items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] no-underline ${
                active ? 'bg-hover font-medium text-fg' : 'text-fg2 hover:bg-hover hover:text-fg'
              }`}
            >
              <Icon name={item.icon} />
              {item.label}
            </Link>
          );
        })}
      </div>

      <div className="flex min-h-0 grow flex-col gap-3.5 overflow-y-auto">
        {conversations === null && (
          <div className="flex flex-col gap-2 px-2.5 pt-1" aria-hidden="true">
            {[0, 1, 2, 3].map((index) => (
              <span key={index} className="h-3 animate-pulse rounded bg-hover" style={{ width: `${80 - index * 12}%` }} />
            ))}
          </div>
        )}
        {conversations?.length === 0 && !pinned?.length && (
          <p className="m-0 px-2.5 text-[12.5px] leading-normal text-fg3">Henüz sohbet yok. İlk sorunuzu sorun.</p>
        )}
        {[...(pinned?.length ? [{ label: 'Sabitlenenler', items: pinned }] : []), ...groups].map((group) => (
          <div key={group.label} className="flex flex-col gap-px">
            <div className="flex items-center gap-1.5 px-2.5 pb-1 text-[11.5px] font-medium text-fg3">
              {group.label === 'Sabitlenenler' && <Icon name="pin" size={12} />}
              {group.label}
            </div>
            {group.items.map((conversation) => (
              <HistoryItem
                key={conversation.id}
                conversation={conversation}
                active={pathname === `/sohbet/${conversation.id}`}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2.5 border-t border-line px-1.5 pb-1 pt-2.5">
        <span className="flex size-[30px] shrink-0 items-center justify-center rounded-full bg-accent-bg text-xs font-semibold text-accent">
          {initials(name)}
        </span>
        <div className="flex min-w-0 grow flex-col">
          <span className="truncate text-[13px] font-medium">{name}</span>
          <span className="text-[11.5px] text-fg3">Kişisel çalışma alanı</span>
        </div>
        <ThemeToggle />
        <button
          type="button"
          onClick={() => void signOut()}
          aria-label="Çıkış yap"
          title="Çıkış yap"
          className="flex size-8 items-center justify-center rounded-lg border border-line bg-surface text-fg2 hover:bg-hover hover:text-fg"
        >
          <Icon name="logout" />
        </button>
      </div>
    </nav>
  );
}

function HistoryItem({
  conversation,
  active,
  onNavigate,
}: {
  conversation: Conversation;
  active: boolean;
  onNavigate?: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  if (renaming) {
    return <RenameField conversation={conversation} onDone={() => setRenaming(false)} className="h-8 text-[13.5px]" />;
  }
  return (
    <div
      data-active={active}
      className={`group flex h-8 items-center rounded-lg pr-0.5 ${active ? 'bg-hover' : 'hover:bg-hover'}`}
    >
      <Link
        href={`/sohbet/${conversation.id}`}
        onClick={onNavigate}
        aria-current={active ? 'page' : undefined}
        title={conversation.title}
        className={`flex h-full min-w-0 grow items-center pl-2.5 pr-1 text-[13.5px] no-underline ${
          active ? 'font-medium text-fg' : 'text-fg2 hover:text-fg'
        }`}
      >
        <span className="truncate">{conversation.title}</span>
      </Link>
      <ConversationMenuButton conversation={conversation} onRename={() => setRenaming(true)} />
    </div>
  );
}
