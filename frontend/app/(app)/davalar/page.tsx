'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Icon, Spinner } from '@/components/icons';
import { api } from '@/lib/api';
import { describeError, formatRelativeDay } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import type { LegalCase } from '@/lib/types';

export default function CasesPage() {
  const now = useNow(60_000);
  const [cases, setCases] = useState<LegalCase[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .listCases()
      .then((page) => {
        if (!active) return;
        setCases(page.items);
        setCursor(page.next_cursor);
      })
      .catch((loadError) => {
        if (active) setError(describeError(loadError));
      });
    return () => {
      active = false;
    };
  }, []);

  const loadMore = async () => {
    if (!cursor) return;
    try {
      const page = await api.listCases(cursor);
      setCases((current) => [...(current ?? []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (loadError) {
      setError(describeError(loadError));
    }
  };

  const create = async () => {
    if (!name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await api.createCase({ name: name.trim(), description: description.trim() || null });
      setCases((current) => [created, ...(current ?? [])]);
      setName('');
      setDescription('');
      setCreating(false);
    } catch (createError) {
      setError(describeError(createError));
    } finally {
      setSaving(false);
    }
  };

  const archive = async (item: LegalCase) => {
    if (!window.confirm(`“${item.name}” davası arşivlensin mi? Sohbetleri silinmez.`)) return;
    try {
      await api.deleteCase(item.id);
      setCases((current) => current?.filter((entry) => entry.id !== item.id) ?? current);
    } catch (archiveError) {
      setError(describeError(archiveError));
    }
  };

  const needle = filter.trim().toLocaleLowerCase('tr-TR');
  const visible = (cases ?? []).filter(
    (item) =>
      !needle ||
      item.name.toLocaleLowerCase('tr-TR').includes(needle) ||
      (item.description ?? '').toLocaleLowerCase('tr-TR').includes(needle),
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[1080px] flex-col gap-6 px-4 py-8 sm:px-8 lg:py-9">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex grow flex-col gap-1.5">
            <h1 className="m-0 text-[26px] font-semibold tracking-[-0.02em]">Davalar</h1>
            <p className="m-0 text-sm text-fg2">Her dava kendi sohbetlerini ve dosyalarını bir arada tutar.</p>
          </div>
          <label className="flex h-9 w-full items-center gap-2 rounded-[9px] border border-line bg-surface px-3 text-fg3 sm:w-[260px]">
            <Icon name="search" size={15} />
            <span className="sr-only">Davalarda ara</span>
            <input
              type="search"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Davalarda ara"
              className="grow border-0 bg-transparent text-[13.5px] text-fg outline-none placeholder:text-fg3"
            />
          </label>
          <button
            type="button"
            onClick={() => setCreating((value) => !value)}
            className="flex h-9 items-center gap-1.5 rounded-[9px] bg-inv px-3.5 text-[13.5px] font-medium text-inv-fg"
          >
            <Icon name="plus" size={15} strokeWidth={2} />
            Yeni dava
          </button>
        </div>

        {creating && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
            className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5"
          >
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              <span className="flex justify-between">
                Dava adı
                <span className="font-mono text-[11.5px] font-normal text-fg3">{name.length} / 160</span>
              </span>
              <input
                autoFocus
                required
                maxLength={160}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Örneğin: Demir Tekstil — ihbar ve kıdem alacağı"
                className="h-10 rounded-[9px] border border-line-strong bg-bg px-3 text-sm font-normal outline-none focus:border-accent"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              <span className="flex justify-between">
                <span>
                  Açıklama <span className="font-normal text-fg3">(isteğe bağlı)</span>
                </span>
                <span className="font-mono text-[11.5px] font-normal text-fg3">{description.length} / 2000</span>
              </span>
              <textarea
                maxLength={2000}
                rows={2}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="resize-y rounded-[9px] border border-line-strong bg-bg px-3 py-2 text-sm font-normal outline-none focus:border-accent"
              />
            </label>
            <div className="flex gap-2">
              <button type="submit" disabled={saving || !name.trim()} className="flex h-9 items-center gap-2 rounded-[9px] bg-inv px-4 text-[13.5px] font-medium text-inv-fg disabled:opacity-50">
                {saving && <Spinner size={14} />}
                Davayı oluştur
              </button>
              <button type="button" onClick={() => setCreating(false)} className="h-9 rounded-[9px] px-3 text-[13.5px] text-fg2 hover:bg-hover">
                Vazgeç
              </button>
            </div>
          </form>
        )}

        {error && (
          <p role="alert" className="m-0 rounded-[10px] border border-err-line bg-err-bg px-3.5 py-2.5 text-[13px] text-err">
            {error}
          </p>
        )}

        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          <div className="hidden h-10 grid-cols-[minmax(0,1fr)_170px_44px] items-center border-b border-line bg-muted pl-5 pr-4 text-[12.5px] font-medium text-fg3 sm:grid">
            <span>Dava</span>
            <span>Son güncelleme</span>
            <span />
          </div>
          {cases === null && !error && (
            <div className="flex items-center gap-3 px-5 py-6 text-sm text-fg3" role="status">
              <Spinner /> Davalar yükleniyor…
            </div>
          )}
          {cases?.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-5 py-12 text-center">
              <Icon name="cases" size={22} className="text-fg3" />
              <p className="m-0 text-sm font-medium">Henüz dava yok</p>
              <p className="m-0 max-w-sm text-[13px] text-fg3">Bir dava oluşturun; sohbetlerinizi ve belgelerinizi aynı yerde toplayın.</p>
            </div>
          )}
          {cases && cases.length > 0 && visible.length === 0 && (
            <p className="m-0 px-5 py-6 text-sm text-fg3">“{filter}” ile eşleşen dava yok.</p>
          )}
          {visible.map((item) => (
            <div key={item.id} className="grid grid-cols-[minmax(0,1fr)_44px] items-center border-b border-line pl-5 pr-4 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_170px_44px]">
              <Link href={`/davalar/${item.id}`} className="flex min-w-0 flex-col gap-1 py-3.5 pr-4 text-fg no-underline">
                <span className="line-clamp-2 text-sm font-medium [overflow-wrap:anywhere]" title={item.name}>
                  {item.name}
                </span>
                <span className="truncate text-[13px] text-fg3">{item.description || 'Açıklama eklenmedi'}</span>
              </Link>
              <span className="hidden text-[13.5px] text-fg2 sm:block">{now ? formatRelativeDay(item.updated_at, now) : ''}</span>
              <button
                type="button"
                onClick={() => void archive(item)}
                aria-label={`${item.name} davasını arşivle`}
                title="Arşivle"
                className="flex size-8 items-center justify-center rounded-lg text-fg3 hover:bg-hover hover:text-fg"
              >
                <Icon name="box" />
              </button>
            </div>
          ))}
        </div>
        {cursor && (
          <button type="button" onClick={() => void loadMore()} className="self-center rounded-full border border-line px-4 py-1.5 text-[13px] text-fg2 hover:bg-hover">
            Daha fazla göster
          </button>
        )}
      </div>
    </div>
  );
}
