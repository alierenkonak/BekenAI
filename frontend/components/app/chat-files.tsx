'use client';

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

export function ChatFileTray({ chatFiles }: { chatFiles: ChatFiles }) {
  const { files, uploads, error } = chatFiles;
  if (!files.length && !uploads.length && !error) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <ul aria-label="Sohbetin dosyaları" className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {uploads.map((item) => (
          <li
            key={item.key}
            className={`flex h-8 max-w-full items-center gap-1.5 rounded-lg border px-2 text-[12.5px] ${item.error ? 'border-err-line bg-err-bg text-err' : 'border-line bg-surface text-fg2'}`}
            title={item.error ?? undefined}
          >
            {item.error ? <Icon name="alert" size={13} /> : <Spinner size={12} />}
            <span className="max-w-[180px] truncate">{item.name}</span>
            {item.error && (
              <button
                type="button"
                onClick={() => chatFiles.dismissUpload(item.key)}
                aria-label="Kapat"
                className="flex size-5 items-center justify-center rounded text-err hover:bg-hover"
              >
                <Icon name="x" size={12} />
              </button>
            )}
          </li>
        ))}
        {files.map((file) => {
          const working = TRANSIENT_STATUSES.has(file.status);
          const failed = file.status === 'failed';
          return (
            <li
              key={file.id}
              title={`${file.original_name} · ${fileDetail(file)}`}
              className={`flex h-8 max-w-full items-center gap-1.5 rounded-lg border px-2 text-[12.5px] ${
                failed ? 'border-err-line bg-err-bg text-err' : 'border-file-line bg-file-bg text-file'
              }`}
            >
              {working ? (
                <Spinner size={12} />
              ) : failed ? (
                <Icon name="alert" size={13} />
              ) : (
                <Icon name="file" size={13} strokeWidth={1.8} />
              )}
              <span className="max-w-[180px] truncate font-medium">{file.original_name}</span>
              {file.status === 'indexing' && file.chunks_total ? (
                <span className="font-mono text-[11px] opacity-80">
                  {file.chunks_done ?? 0}/{file.chunks_total}
                </span>
              ) : null}
              {file.status !== 'delete_pending' && (
                <button
                  type="button"
                  onClick={() => void chatFiles.remove(file)}
                  aria-label={`${file.original_name} dosyasını sil`}
                  className="flex size-5 items-center justify-center rounded opacity-70 hover:bg-hover hover:opacity-100"
                >
                  <Icon name="x" size={12} />
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {error && <p className="m-0 text-[12.5px] text-err">{error}</p>}
      {files
        .filter((file) => file.status === 'failed')
        .map((file) => (
          <p key={file.id} className="m-0 text-[12.5px] text-err">
            {file.original_name}: {describeError(file.safe_error_code ?? 'job_failed')}
          </p>
        ))}
    </div>
  );
}
