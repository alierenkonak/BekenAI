'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon, Spinner } from '@/components/icons';
import { Badge } from '@/components/ui';
import { api } from '@/lib/api';
import { FILE_ACCEPT, SAMPLE_FILE_URL, TRANSIENT_STATUSES, fileDetail, mediaTypeOf, uploadProblem } from '@/lib/files';
import { describeError, formatBytes, formatRelativeDay, isRetryableIngestFailure } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import type { Conversation, LegalCase, UserFile } from '@/lib/types';

type LocalUpload = { key: string; name: string; size: number; error: string | null };

const FILE_STATUS: Record<UserFile['status'], { label: string; tone: 'ok' | 'accent' | 'neutral' | 'err' }> = {
  pending_upload: { label: 'Yükleme bekleniyor', tone: 'neutral' },
  verifying: { label: 'Doğrulanıyor', tone: 'accent' },
  uploaded: { label: 'Sırada', tone: 'neutral' },
  indexing: { label: 'İşleniyor', tone: 'accent' },
  ready: { label: 'Hazır', tone: 'ok' },
  failed: { label: 'Hata', tone: 'err' },
  delete_pending: { label: 'Siliniyor', tone: 'neutral' },
  deleted: { label: 'Silindi', tone: 'neutral' },
};

export function CaseDetail({ caseId }: { caseId: string }) {
  const now = useNow(60_000);
  const [legalCase, setLegalCase] = useState<LegalCase | null>(null);
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [files, setFiles] = useState<UserFile[] | null>(null);
  const [uploads, setUploads] = useState<LocalUpload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    Promise.all([api.getCase(caseId), api.listConversations({ caseId }), api.listFiles(caseId)])
      .then(([loadedCase, conversationPage, filePage]) => {
        if (!active) return;
        setLegalCase(loadedCase);
        setConversations(conversationPage.items);
        setFiles(filePage.items);
      })
      .catch((loadError) => {
        if (active) setError(describeError(loadError));
      });
    return () => {
      active = false;
    };
  }, [caseId]);

  const reloadFiles = useCallback(async () => {
    const page = await api.listFiles(caseId);
    setFiles(page.items);
  }, [caseId]);

  const pending = files?.some((file) => TRANSIENT_STATUSES.has(file.status)) ?? false;
  useEffect(() => {
    if (!pending) return;
    const interval = window.setInterval(() => {
      reloadFiles().catch(() => {});
    }, 2000);
    return () => window.clearInterval(interval);
  }, [pending, reloadFiles]);

  const upload = async (file: File) => {
    const key = `${file.name}-${file.size}-${file.lastModified}`;
    const mediaType = mediaTypeOf(file);
    const problem = uploadProblem(file);
    setUploads((current) => [...current.filter((item) => item.key !== key), { key, name: file.name, size: file.size, error: problem }]);
    if (problem || !mediaType) return;
    try {
      await api.uploadFile(caseId, file, mediaType);
      setUploads((current) => current.filter((item) => item.key !== key));
      await reloadFiles();
    } catch (uploadError) {
      setUploads((current) => current.map((item) => (item.key === key ? { ...item, error: describeError(uploadError) } : item)));
      await reloadFiles().catch(() => {});
    }
  };

  const onFiles = (list: FileList | null) => {
    if (!list) return;
    for (const file of Array.from(list)) void upload(file);
  };

  const download = async (file: UserFile) => {
    try {
      const { url } = await api.downloadUrl(file.id);
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (downloadError) {
      setError(describeError(downloadError));
    }
  };

  const reindex = async (file: UserFile) => {
    try {
      const updated = await api.reindexFile(file.id);
      setFiles((current) => current?.map((item) => (item.id === file.id ? updated : item)) ?? current);
    } catch (reindexError) {
      setError(describeError(reindexError));
    }
  };

  const remove = async (file: UserFile) => {
    if (!window.confirm(`“${file.original_name}” silinsin mi?`)) return;
    try {
      const updated = await api.deleteFile(file.id);
      setFiles((current) => current?.map((item) => (item.id === file.id ? updated : item)) ?? current);
    } catch (deleteError) {
      setError(describeError(deleteError));
    }
  };

  const save = async () => {
    if (!name.trim()) return;
    try {
      const updated = await api.updateCase(caseId, { name: name.trim(), description: description.trim() || null });
      setLegalCase(updated);
      setEditing(false);
    } catch (saveError) {
      setError(describeError(saveError));
    }
  };

  const usedBytes = (files ?? []).reduce((sum, file) => sum + (file.verified_size_bytes ?? file.expected_size_bytes), 0);

  if (!legalCase) {
    return (
      <div className="flex h-full items-center justify-center gap-3 px-6 text-sm text-fg3" role="status">
        {error ? (
          <span className="flex flex-col items-center gap-3 text-center">
            {error}
            <Link href="/davalar" className="text-fg2 underline">
              Davalara dön
            </Link>
          </span>
        ) : (
          <>
            <Spinner /> Dava yükleniyor…
          </>
        )}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-6 px-4 py-7 sm:px-8">
        <nav aria-label="Konum" className="flex items-center gap-1.5 text-[13px] text-fg3">
          <Link href="/davalar" className="text-fg2 no-underline hover:text-fg">
            Davalar
          </Link>
          <Icon name="chevRight" size={13} />
          <span className="truncate">{legalCase.name}</span>
        </nav>

        {editing ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
            className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5"
          >
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Dava adı
              <input
                autoFocus
                required
                maxLength={160}
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="h-10 rounded-[9px] border border-line-strong bg-bg px-3 text-sm font-normal outline-none focus:border-accent"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Açıklama
              <textarea
                maxLength={2000}
                rows={3}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="resize-y rounded-[9px] border border-line-strong bg-bg px-3 py-2 text-sm font-normal outline-none focus:border-accent"
              />
            </label>
            <div className="flex gap-2">
              <button type="submit" className="h-9 rounded-[9px] bg-inv px-4 text-[13.5px] font-medium text-inv-fg">
                Kaydet
              </button>
              <button type="button" onClick={() => setEditing(false)} className="h-9 rounded-[9px] px-3 text-[13.5px] text-fg2 hover:bg-hover">
                Vazgeç
              </button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap items-start gap-4">
            <div className="flex min-w-0 grow flex-col gap-1.5">
              <h1 className="m-0 text-[26px] font-semibold tracking-[-0.02em]">{legalCase.name}</h1>
              {legalCase.description && <p className="m-0 max-w-[640px] text-sm leading-normal text-fg2">{legalCase.description}</p>}
            </div>
            <button
              type="button"
              onClick={() => {
                setName(legalCase.name);
                setDescription(legalCase.description ?? '');
                setEditing(true);
              }}
              className="h-9 rounded-[9px] border border-line-strong bg-surface px-3.5 text-[13.5px] font-medium text-fg hover:bg-hover"
            >
              Düzenle
            </button>
            <Link
              href={`/sohbet?dava=${caseId}`}
              className="flex h-9 items-center gap-1.5 rounded-[9px] bg-inv px-3.5 text-[13.5px] font-medium text-inv-fg no-underline"
            >
              <Icon name="plus" size={15} strokeWidth={2} />
              Bu davada yeni sohbet
            </Link>
          </div>
        )}

        {error && (
          <p role="alert" className="m-0 rounded-[10px] border border-err-line bg-err-bg px-3.5 py-2.5 text-[13px] text-err">
            {error}
          </p>
        )}

        <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
          <section className="flex flex-col rounded-[14px] border border-line bg-surface">
            <header className="flex h-[52px] items-center gap-2 border-b border-line px-5">
              <h2 className="m-0 text-[14.5px] font-semibold">Sohbetler</h2>
              <span className="text-[13px] text-fg3">{conversations?.length ?? ''}</span>
            </header>
            {conversations?.length === 0 && (
              <p className="m-0 px-5 py-6 text-[13.5px] text-fg3">Bu davaya bağlı sohbet yok. İlk soruyu sorun.</p>
            )}
            {conversations?.map((conversation) => (
              <Link
                key={conversation.id}
                href={`/sohbet/${conversation.id}`}
                className="flex items-center gap-2 border-b border-line px-5 py-4 text-fg no-underline last:border-b-0 hover:bg-hover"
              >
                <span className="min-w-0 grow truncate text-sm font-medium">{conversation.title}</span>
                {conversation.doctrine_enabled && (
                  <Badge tone="doc">
                    <span className="size-1.5 rounded-[2px] bg-doc" />
                    Doktrin
                  </Badge>
                )}
                <span className="shrink-0 text-[12.5px] text-fg3">{now ? formatRelativeDay(conversation.updated_at, now) : ''}</span>
              </Link>
            ))}
          </section>

          <section className="flex flex-col gap-3.5 rounded-[14px] border border-line bg-surface px-5 pb-5 pt-[18px]">
            <header className="flex items-center gap-2">
              <h2 className="m-0 text-[14.5px] font-semibold">Dosyalar</h2>
              <span className="text-[13px] text-fg3">{files?.length ?? ''}</span>
              <span className="grow" />
              <span className="text-[12.5px] text-fg3">{formatBytes(usedBytes)} kullanılıyor</span>
            </header>

            <div
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                onFiles(event.dataTransfer.files);
              }}
              className={`flex flex-col items-center gap-2 rounded-xl border-[1.5px] border-dashed p-5 text-center transition-colors ${
                dragging ? 'border-accent bg-accent-bg' : 'border-line-strong bg-muted'
              }`}
            >
              <span className="flex size-9 items-center justify-center rounded-[10px] border border-line bg-surface text-fg2">
                <Icon name="upload" size={17} />
              </span>
              <span className="text-[13.5px] font-medium">
                Dosyayı buraya sürükleyin veya{' '}
                <button type="button" onClick={() => inputRef.current?.click()} className="font-medium text-accent underline">
                  bilgisayardan seçin
                </button>
              </span>
              <span className="text-[12.5px] text-fg3">PDF, Word (DOCX) veya TXT · dosya başına en fazla 50 MB</span>
              <a href={SAMPLE_FILE_URL} download className="text-[12.5px] font-medium text-file underline">
                Elinizde dosya yok mu? Kurgusal örnek dava dosyasını indirin
              </a>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept={FILE_ACCEPT}
                className="sr-only"
                onChange={(event) => {
                  onFiles(event.target.files);
                  event.target.value = '';
                }}
              />
            </div>

            <ul className="m-0 flex list-none flex-col p-0">
              {uploads.map((item) => (
                <li key={item.key} className="flex items-center gap-3 border-b border-line py-2.5 last:border-b-0">
                  <Icon name="file" size={18} strokeWidth={1.6} className={item.error ? 'text-err' : 'text-fg3'} />
                  <div className="flex min-w-0 grow flex-col">
                    <span className="truncate text-[13.5px] font-medium">{item.name}</span>
                    <span className={`text-xs ${item.error ? 'text-err' : 'text-fg3'}`}>{item.error ?? `${formatBytes(item.size)} · yükleniyor`}</span>
                  </div>
                  {item.error ? (
                    <button
                      type="button"
                      onClick={() => setUploads((current) => current.filter((entry) => entry.key !== item.key))}
                      aria-label="Kapat"
                      className="flex size-7 items-center justify-center rounded-[7px] text-fg3 hover:bg-hover"
                    >
                      <Icon name="x" size={14} />
                    </button>
                  ) : (
                    <Spinner size={16} className="text-accent" />
                  )}
                </li>
              ))}
              {files?.map((file) => {
                const status = FILE_STATUS[file.status];
                return (
                  <li key={file.id} className="flex items-center gap-3 border-b border-line py-2.5 last:border-b-0">
                    <Icon name="file" size={18} strokeWidth={1.6} className={file.status === 'failed' ? 'text-err' : 'text-fg3'} />
                    <div className="flex min-w-0 grow flex-col">
                      <span className="truncate text-[13.5px] font-medium">{file.original_name}</span>
                      <span className={`text-xs ${file.status === 'failed' ? 'text-err' : 'text-fg3'}`}>{fileDetail(file)}</span>
                    </div>
                    <Badge tone={status.tone}>
                      {(file.status === 'verifying' || file.status === 'indexing') && <Spinner size={11} />}
                      {file.status === 'ready' && <Icon name="check" size={12} strokeWidth={2.4} />}
                      {status.label}
                    </Badge>
                    {file.status === 'failed' && file.verified_size_bytes !== null && isRetryableIngestFailure(file.safe_error_code) && (
                      <button
                        type="button"
                        onClick={() => void reindex(file)}
                        aria-label={`${file.original_name} dosyasını yeniden işle`}
                        title="Yeniden dene"
                        className="flex size-7 items-center justify-center rounded-[7px] text-fg3 hover:bg-hover hover:text-fg"
                      >
                        <Icon name="refresh" size={14} />
                      </button>
                    )}
                    {file.verified_size_bytes !== null && file.status !== 'delete_pending' && file.status !== 'deleted' && (
                      <button
                        type="button"
                        onClick={() => void download(file)}
                        aria-label={`${file.original_name} dosyasını indir`}
                        className="flex size-7 items-center justify-center rounded-[7px] text-fg3 hover:bg-hover hover:text-fg"
                      >
                        <Icon name="download" size={14} />
                      </button>
                    )}
                    {file.status !== 'verifying' && file.status !== 'delete_pending' && file.status !== 'deleted' && (
                      <button
                        type="button"
                        onClick={() => void remove(file)}
                        aria-label={`${file.original_name} dosyasını sil`}
                        className="flex size-7 items-center justify-center rounded-[7px] text-fg3 hover:bg-hover hover:text-err"
                      >
                        <Icon name="trash" size={14} />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>

            <p className="m-0 flex items-start gap-2 text-[12.5px] leading-normal text-fg3">
              <Icon name="lock" size={14} className="mt-0.5" />
              Dosyalar yalnızca sizin çalışma alanınızda saklanır; ortak kaynak havuzuna hiçbir zaman eklenmez.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
