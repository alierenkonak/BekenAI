'use client';

import { API_URL } from './config';
import { getAccessToken, getSupabase } from './supabase';
import type {
  ChatEnqueued,
  Conversation,
  GenerationDetail,
  LegalCase,
  Message,
  Page,
  SearchResponse,
  UploadIntent,
  UserFile,
} from './types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
    this.name = 'ApiError';
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new ApiError(401, 'authentication_required');
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: options.method ?? 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...options.headers,
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: 'no-store',
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'network_unreachable');
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === 'object' ? (data as { detail?: unknown }).detail : null;
    const code =
      detail && typeof detail === 'object' && 'code' in detail
        ? String((detail as { code: unknown }).code)
        : response.status === 422
          ? 'validation_failed'
          : 'request_failed';
    throw new ApiError(response.status, code);
  }
  return data as T;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export const api = {
  bootstrap: () => request<unknown>('/me/bootstrap', { method: 'POST' }),

  listConversations: (params: { caseId?: string; cursor?: string | null; limit?: number } = {}) =>
    request<Page<Conversation>>(
      `/conversations${query({ case_id: params.caseId, cursor: params.cursor, limit: params.limit ?? 50 })}`,
    ),
  getConversation: (id: string) => request<Conversation>(`/conversations/${id}`),
  updateConversation: (id: string, patch: { title?: string; case_id?: string | null; include_doctrine?: boolean }) =>
    request<Conversation>(`/conversations/${id}`, { method: 'PATCH', body: patch }),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: 'DELETE' }),
  listMessages: (id: string, cursor?: string | null) =>
    request<Page<Message>>(`/conversations/${id}/messages${query({ cursor, limit: 50 })}`),

  sendChat: (
    payload: { conversation_id?: string; case_id?: string | null; message: string; include_doctrine: boolean },
    idempotencyKey: string,
  ) =>
    request<ChatEnqueued>('/chat', {
      method: 'POST',
      body: { ...payload, domain: 'labour_law' },
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
  getGeneration: (id: string, signal?: AbortSignal) =>
    request<GenerationDetail>(`/chat/generations/${id}`, { signal }),
  cancelGeneration: (id: string) => request<unknown>(`/chat/generations/${id}/cancel`, { method: 'POST' }),

  listCases: (cursor?: string | null) => request<Page<LegalCase>>(`/cases${query({ cursor, limit: 50 })}`),
  getCase: (id: string) => request<LegalCase>(`/cases/${id}`),
  createCase: (payload: { name: string; description: string | null }) =>
    request<LegalCase>('/cases', { method: 'POST', body: payload }),
  updateCase: (id: string, payload: { name?: string; description?: string | null }) =>
    request<LegalCase>(`/cases/${id}`, { method: 'PATCH', body: payload }),
  deleteCase: (id: string) => request<void>(`/cases/${id}`, { method: 'DELETE' }),

  listFiles: (caseId: string) => request<{ items: UserFile[] }>(`/cases/${caseId}/files`),
  fileStatus: (id: string) => request<UserFile>(`/files/${id}/status`),
  downloadUrl: (id: string) => request<{ url: string }>(`/files/${id}/download-url`, { method: 'POST' }),
  deleteFile: (id: string) => request<UserFile>(`/files/${id}`, { method: 'DELETE' }),

  /** Intent → direct Storage upload with the user's JWT → server-side verification job. */
  async uploadFile(caseId: string, file: File, mediaType: 'application/pdf' | 'text/plain'): Promise<UserFile> {
    const intent = await request<UploadIntent>(`/cases/${caseId}/files/upload-intent`, {
      method: 'POST',
      body: { filename: file.name, media_type: mediaType, size_bytes: file.size },
    });
    const supabase = getSupabase();
    if (!supabase) throw new ApiError(401, 'authentication_required');
    try {
      const { error } = await supabase.storage
        .from(intent.upload.bucket)
        .upload(intent.upload.path, file, { contentType: mediaType, upsert: false });
      if (error) throw new ApiError(503, 'storage_temporarily_unavailable');
    } catch {
      // The intent reserves quota. Queue deletion even when Storage rejected the upload;
      // the worker treats an absent object as already deleted.
      await request<UserFile>(`/files/${intent.file.id}`, { method: 'DELETE' }).catch(() => {});
      throw new ApiError(503, 'storage_temporarily_unavailable');
    }
    return request<UserFile>(`/files/${intent.file.id}/complete`, { method: 'POST' });
  },

  search: (payload: { query: string; include_doctrine: boolean; limit?: number }, signal?: AbortSignal) =>
    request<SearchResponse>('/search', {
      method: 'POST',
      body: { query: payload.query, include_doctrine: payload.include_doctrine, limit: payload.limit ?? 10 },
      signal,
    }),
};
