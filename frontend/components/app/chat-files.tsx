'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon, Spinner } from '@/components/icons';
import { api } from '@/lib/api';
import {
  FILE_ACCEPT,
  PROCESSING_STATUSES,
  TRANSIENT_STATUSES,
  fileDetail,
  indexingProgress,
  mediaTypeOf,
  uploadProblem,
} from '@/lib/files';
import { describeError } from '@/lib/format';
import type { UserFile } from '@/lib/types';
import { Popover } from './popover';

type LocalUpload = { key: string; name: string; error: string | null };

const HANDOFF_PREFIX = 'bekenai-draft:';

/** Carries an unsent question across the jump from "new chat" to the chat created for a file. */
export function saveDraftHandoff(conversationId: string, draft: string) {
  try {
    if (draft.trim()) window.sessionStorage.setItem(HANDOFF_PREFIX + conversationId, draft);
  } catch {
    // Storage may be unavailable (private mode); the draft is a convenience only.
  }
}

export function readDraftHandoff(conversationId: string): string {
  if (typeof window === 'undefined') return '';
  try {
    return window.sessionStorage.getItem(HANDOFF_PREFIX + conversationId) ?? '';
  } catch {
    return '';
  }
}

export function clearDraftHandoff(conversationId: string) {
  try {
    window.sessionStorage.removeItem(HANDOFF_PREFIX + conversationId);
  } catch {
    // Nothing to clear.
  }
}

/** The files a chat can read, kept fresh while the worker verifies and indexes them. */
export function useChatFiles(conversationId: string) {
  const [files, setFiles] = useState<UserFile[] | null>(null);
  const [uploads, setUploads] = useState<LocalUpload[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const page = await api.listConversationFiles(conversationId);
    setFiles(page.items);
  }, [conversationId]);

  useEffect(() => {
    let active = true;
    api
      .listConversationFiles(conversationId)
      .then((page) => {
        if (active) setFiles(page.items);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [conversationId]);

  const pending = files?.some((file) => TRANSIENT_STATUSES.has(file.status)) ?? false;
  useEffect(() => {
    if (!pending) return;
    const interval = window.setInterval(() => {
      reload().catch(() => {});
    }, 2000);
    return () => window.clearInterval(interval);
  }, [pending, reload]);

  const upload = async (file: File) => {
    const key = `${file.name}-${file.size}-${file.lastModified}`;
    const problem = uploadProblem(file);
    const mediaType = mediaTypeOf(file);
    setUploads((current) => [...current.filter((item) => item.key !== key), { key, name: file.name, error: problem }]);
    if (problem || !mediaType) return;
    try {
      await api.uploadConversationFile(conversationId, file, mediaType);
      setUploads((current) => current.filter((item) => item.key !== key));
    } catch (uploadError) {
      setUploads((current) => current.map((item) => (item.key === key ? { ...item, error: describeError(uploadError) } : item)));
    }
    await reload().catch(() => {});
  };

  const remove = async (file: UserFile) => {
    const note = file.case_id ? ' Dosya davadan da silinir.' : '';
    if (!window.confirm(`“${file.original_name}” silinsin mi?${note}`)) return;
    try {
      const updated = await api.deleteFile(file.id);
      setFiles((current) => current?.map((item) => (item.id === file.id ? updated : item)) ?? current);
    } catch (removeError) {
      setError(describeError(removeError));
    }
  };

  const dismissUpload = (key: string) => setUploads((current) => current.filter((item) => item.key !== key));

  const processing = (files ?? []).filter((file) => PROCESSING_STATUSES.has(file.status));
  const uploading = uploads.filter((item) => !item.error).length;
  return {
    files: (files ?? []).filter((file) => file.status !== 'deleted'),
    uploads,
    error,
    processing,
    busy: processing.length > 0 || uploading > 0,
    reload,
    upload,
    remove,
    dismissUpload,
  };
}

export type ChatFiles = ReturnType<typeof useChatFiles>;

export function AttachButton({ onFiles, disabled = false }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        aria-label="Dosya ekle"
        title="Dosya ekle · PDF, Word (DOCX) veya TXT"
        className="flex size-8 items-center justify-center rounded-lg text-fg2 hover:bg-hover hover:text-fg disabled:opacity-40"
      >
        <Icon name="clip" size={16} />
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={FILE_ACCEPT}
        className="sr-only"
        tabIndex={-1}
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
    </>
  );
}

/** One line for the composer while the chat must wait for its files. */
export function processingNote(chatFiles: ChatFiles): string | null {
  const [first] = chatFiles.processing;
  if (first) {
    const more = chatFiles.processing.length > 1 ? ` (+${chatFiles.processing.length - 1} dosya)` : '';
    const progress = first.status === 'indexing' ? indexingProgress(first) : 'doğrulanıyor';
    return `${first.original_name}${more} işleniyor · ${progress}. Tamamlanınca soru sorabilirsiniz.`;
  }
  return chatFiles.busy ? 'Dosya yükleniyor…' : null;
}

/**
 * The chat's files behind a header button, so they stay findable without sitting above the
 * composer. Lists each file with its state; uploads that failed and files that could not be
 * read are flagged on the button.
 */
export function ChatFilesButton({ chatFiles, caseId }: { chatFiles: ChatFiles; caseId: string | null }) {
  const { files, uploads, error } = chatFiles;
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const pending = uploads.filter((item) => !item.error);
  if (!files.length && !uploads.length) return null;
  const failed = uploads.some((item) => item.error) || files.some((file) => file.status === 'failed');

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] font-medium text-fg2 hover:bg-hover hover:text-fg"
      >
        {chatFiles.busy ? <Spinner size={13} className="text-file" /> : <Icon name="file" size={14} />}
        <span className="hidden sm:inline">Dosyalar</span>
        <span className="text-fg3">{files.length + pending.length}</span>
        {failed && <span aria-label="Sorunlu dosya var" className="size-1.5 rounded-full bg-err" />}
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={triggerRef}
        placement="bottom-end"
        role="dialog"
        aria-label="Sohbetin dosyaları"
        className="w-[min(360px,calc(100vw-16px))] p-0"
      >
        <div className="flex items-center gap-2 border-b border-line px-3.5 py-2.5">
          <span className="grow text-[13px] font-semibold">{caseId ? 'Davanın dosyaları' : 'Bu sohbetin dosyaları'}</span>
          {caseId && (
            <Link href={`/davalar/${caseId}`} className="text-[12.5px] text-fg2 underline hover:text-fg">
              Dava sayfası
            </Link>
          )}
        </div>
        <ul className="m-0 flex max-h-[min(360px,60vh)] list-none flex-col overflow-y-auto p-1.5">
          {uploads.map((item) => (
            <li key={item.key} className="flex items-center gap-2.5 rounded-lg px-2 py-2">
              {item.error ? <Icon name="alert" size={15} className="shrink-0 text-err" /> : <Spinner size={14} className="shrink-0 text-file" />}
              <span className="flex min-w-0 grow flex-col">
                <span className="truncate text-[13px] font-medium">{item.name}</span>
                <span className={`text-xs ${item.error ? 'text-err' : 'text-fg3'}`}>{item.error ?? 'Yükleniyor…'}</span>
              </span>
              {item.error && (
                <button
                  type="button"
                  onClick={() => chatFiles.dismissUpload(item.key)}
                  aria-label="Kapat"
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-fg3 hover:bg-hover hover:text-fg"
                >
                  <Icon name="x" size={13} />
                </button>
              )}
            </li>
          ))}
          {files.map((file) => {
            const working = TRANSIENT_STATUSES.has(file.status);
            const broken = file.status === 'failed';
            return (
              <li key={file.id} className="flex items-center gap-2.5 rounded-lg px-2 py-2">
                {working ? (
                  <Spinner size={14} className="shrink-0 text-file" />
                ) : (
                  <Icon name={broken ? 'alert' : 'file'} size={15} className={`shrink-0 ${broken ? 'text-err' : 'text-file'}`} />
                )}
                <span className="flex min-w-0 grow flex-col">
                  <span className="truncate text-[13px] font-medium" title={file.original_name}>
                    {file.original_name}
                  </span>
                  <span className={`truncate text-xs ${broken ? 'text-err' : 'text-fg3'}`}>
                    {file.status === 'delete_pending' ? 'Siliniyor…' : fileDetail(file)}
                  </span>
                </span>
                {file.status !== 'delete_pending' && file.status !== 'verifying' && (
                  <button
                    type="button"
                    onClick={() => void chatFiles.remove(file)}
                    aria-label={`${file.original_name} dosyasını sil`}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-fg3 hover:bg-hover hover:text-err"
                  >
                    <Icon name="trash" size={13} />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
        {error && <p className="m-0 border-t border-line px-3.5 py-2.5 text-[12.5px] text-err">{error}</p>}
      </Popover>
    </>
  );
}
