'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Icon, Spinner } from '@/components/icons';
import { api } from '@/lib/api';
import { renderAnswer, type RenderedAnswer } from '@/lib/answer';
import { describeError } from '@/lib/format';
import type { Conversation, GenerationSummary, Message } from '@/lib/types';
import { AnswerView, CancelledCard, FailedCard, InsufficientCard } from './answer';
import { Composer } from './composer';
import { useConversations } from './conversations';
import { GenerationProgress } from './generation-progress';
import { PromptRail } from './prompt-rail';
import { SourcePanel } from './source-panel';

type Turn = {
  user: Message;
  generation: GenerationSummary | null;
  assistant: Message | null;
  rendered: RenderedAnswer | null;
};

const timeFormatter = new Intl.DateTimeFormat('tr-TR', { hour: '2-digit', minute: '2-digit' });

function buildTurns(messages: Message[]): Turn[] {
  const assistants = new Map(messages.filter((message) => message.role === 'assistant').map((message) => [message.id, message]));
  return messages
    .filter((message) => message.role === 'user')
    .map((user) => {
      const generation = user.generation;
      const assistant = generation?.assistant_message_id ? (assistants.get(generation.assistant_message_id) ?? null) : null;
      const structured = assistant?.structured_content;
      const rendered =
        structured && structured.answer_status === 'answered' ? renderAnswer(structured, assistant?.citations ?? []) : null;
      return { user, generation, assistant, rendered };
    });
}

function isActive(generation: GenerationSummary | null): boolean {
  return generation?.status === 'queued' || generation?.status === 'processing';
}

export function ConversationView({ conversationId }: { conversationId: string }) {
  const router = useRouter();
  const { refresh: refreshSidebar } = useConversations();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [caseName, setCaseName] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [olderCursor, setOlderCursor] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [draft, setDraft] = useState('');
  const [doctrineOverride, setDoctrineOverride] = useState<boolean | null>(null);
  const [sending, setSending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [selected, setSelected] = useState<{ messageId: string; sourceId: string } | null>(null);
  const [activePrompt, setActivePrompt] = useState(0);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    let active = true;
    Promise.all([api.getConversation(conversationId), api.listMessages(conversationId)])
      .then(([loaded, page]) => {
        if (!active) return;
        setConversation(loaded);
        setMessages([...page.items].reverse());
        setOlderCursor(page.next_cursor);
        setLoadError(null);
      })
      .catch((error) => {
        if (active) setLoadError(describeError(error));
      });
    return () => {
      active = false;
    };
  }, [conversationId, reloadKey]);

  const caseId = conversation?.case_id ?? null;
  useEffect(() => {
    if (!caseId) return;
    let active = true;
    api
      .getCase(caseId)
      .then((loaded) => {
        if (active) setCaseName(loaded.name);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [caseId]);

  const turns = useMemo(() => (messages ? buildTurns(messages) : []), [messages]);
  const activeGeneration = useMemo(() => [...turns].reverse().find((turn) => isActive(turn.generation))?.generation ?? null, [turns]);
  const activeId = activeGeneration?.id ?? null;
  const includeDoctrine = doctrineOverride ?? conversation?.doctrine_enabled ?? false;

  // Poll the running generation; on a terminal state reload messages with citations.
  useEffect(() => {
    if (!activeId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const detail = await api.getGeneration(activeId);
        if (stopped) return;
        if (detail.status === 'queued' || detail.status === 'processing') {
          setMessages((current) =>
            current
              ? current.map((message) =>
                  message.generation && message.generation.id === activeId
                    ? { ...message, generation: { ...message.generation, status: detail.status, stage: detail.stage } }
                    : message,
                )
              : current,
          );
        } else {
          setReloadKey((value) => value + 1);
          refreshSidebar();
        }
      } catch {
        // Transient polling failures are retried on the next tick.
      }
    };
    const first = window.setTimeout(poll, 800);
    const interval = window.setInterval(poll, 2000);
    return () => {
      stopped = true;
      window.clearTimeout(first);
      window.clearInterval(interval);
    };
  }, [activeId, refreshSidebar]);

  // Keep the newest turn in view while the reader is already at the bottom.
  const lastTurnKey = turns.length ? `${turns[turns.length - 1].user.id}:${turns[turns.length - 1].generation?.status}` : '';
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller && stickToBottom.current) scroller.scrollTop = scroller.scrollHeight;
  }, [lastTurnKey]);

  const onScroll = useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 48;
    stickToBottom.current = atBottom;
    const sections = scroller.querySelectorAll<HTMLElement>('[data-turn]');
    let current = 0;
    sections.forEach((section, index) => {
      if (section.offsetTop - 120 <= scroller.scrollTop) current = index;
    });
    setActivePrompt(atBottom ? Math.max(0, sections.length - 1) : current);
  }, []);

  const jumpTo = (index: number) => {
    const scroller = scrollerRef.current;
    const section = scroller?.querySelector<HTMLElement>(`[data-turn="${index}"]`);
    if (!scroller || !section) return;
    scroller.scrollTo({ top: section.offsetTop - 16, behavior: 'smooth' });
    setActivePrompt(index);
  };

  const send = async (text: string) => {
    const message = text.trim();
    if (message.length < 3 || sending) return;
    setSending(true);
    setActionError(null);
    try {
      const queued = await api.sendChat(
        { conversation_id: conversationId, message, include_doctrine: includeDoctrine },
        crypto.randomUUID(),
      );
      const createdAt = new Date().toISOString();
      setMessages((current) => [
        ...(current ?? []),
        {
          id: queued.user_message_id,
          conversation_id: conversationId,
          role: 'user',
          content: message,
          structured_content: null,
          status: 'completed',
          created_at: createdAt,
          generation: {
            id: queued.generation_id,
            user_message_id: queued.user_message_id,
            assistant_message_id: null,
            status: queued.status,
            stage: null,
            answer_status: null,
            safe_error_code: null,
            include_doctrine: includeDoctrine,
            latency_ms: null,
            corpus_versions: {},
            index_versions: {},
            created_at: createdAt,
            started_at: null,
            completed_at: null,
          },
        },
      ]);
      setDraft('');
      stickToBottom.current = true;
      refreshSidebar();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setSending(false);
    }
  };

  const cancel = async (generationId: string) => {
    setCancelling(true);
    try {
      await api.cancelGeneration(generationId);
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setCancelling(false);
      setReloadKey((value) => value + 1);
    }
  };

  const changeDoctrine = (value: boolean) => {
    setDoctrineOverride(value);
    void api.updateConversation(conversationId, { include_doctrine: value }).catch(() => {});
  };

  const loadOlder = async () => {
    const scroller = scrollerRef.current;
    if (!olderCursor) return;
    const previousHeight = scroller?.scrollHeight ?? 0;
    try {
      const page = await api.listMessages(conversationId, olderCursor);
      setMessages((current) => [...[...page.items].reverse(), ...(current ?? [])]);
      setOlderCursor(page.next_cursor);
      window.requestAnimationFrame(() => {
        if (scroller) scroller.scrollTop += scroller.scrollHeight - previousHeight;
      });
    } catch (error) {
      setActionError(describeError(error));
    }
  };

  const removeConversation = async () => {
    if (!window.confirm('Bu sohbet ve tüm cevapları kalıcı olarak silinsin mi?')) return;
    try {
      await api.deleteConversation(conversationId);
      refreshSidebar();
      router.push('/sohbet');
    } catch (error) {
      setActionError(describeError(error));
    }
  };

  const selectedTurn = selected ? turns.find((turn) => turn.assistant?.id === selected.messageId) : undefined;
  const selectedSource = selectedTurn?.rendered?.sources.find((source) => source.sourceId === selected?.sourceId) ?? null;

  if (loadError && !messages) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="m-0 text-sm text-fg2">{loadError}</p>
        <div className="flex gap-2">
          <button type="button" onClick={() => setReloadKey((value) => value + 1)} className="h-9 rounded-[9px] bg-inv px-4 text-[13.5px] font-medium text-inv-fg">
            Tekrar dene
          </button>
          <Link href="/sohbet" className="flex h-9 items-center rounded-[9px] border border-line-strong px-4 text-[13.5px] font-medium text-fg no-underline">
            Yeni sohbet
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 grow flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4 sm:px-6">
          <h1 className="m-0 min-w-0 truncate text-sm font-medium">{conversation?.title ?? 'Sohbet'}</h1>
          {caseId && (
            <Link
              href={`/davalar/${caseId}`}
              className="hidden h-6 min-w-0 items-center gap-1.5 rounded-md bg-muted px-2 text-xs text-fg2 no-underline hover:text-fg sm:flex"
            >
              <Icon name="cases" size={13} />
              <span className="truncate">{caseName ?? 'Dava'}</span>
            </Link>
          )}
          <span className="grow" />
          {turns.length > 0 && <span className="hidden text-[12.5px] text-fg3 sm:inline">{turns.length} soru</span>}
          <button
            type="button"
            onClick={() => void removeConversation()}
            aria-label="Sohbeti sil"
            title="Sohbeti sil"
            className="flex size-8 items-center justify-center rounded-lg text-fg3 hover:bg-hover hover:text-err"
          >
            <Icon name="trash" />
          </button>
        </header>

        <div className="relative flex min-h-0 grow">
          <div ref={scrollerRef} onScroll={onScroll} className="relative min-h-0 grow overflow-y-auto">
            <div className="mx-auto flex w-full max-w-[640px] flex-col gap-10 px-4 py-7 sm:px-6 lg:px-0">
              {!messages && (
                <div className="flex items-center gap-3 text-sm text-fg3" role="status">
                  <Spinner />
                  Sohbet yükleniyor…
                </div>
              )}
              {olderCursor && (
                <button type="button" onClick={() => void loadOlder()} className="self-center rounded-full border border-line px-3.5 py-1.5 text-[12.5px] text-fg2 hover:bg-hover">
                  Daha eski mesajları yükle
                </button>
              )}
              {messages && turns.length === 0 && (
                <p className="m-0 text-center text-sm text-fg3">Bu sohbette henüz soru yok. Aşağıdan ilk sorunuzu yazın.</p>
              )}
              {turns.map((turn, index) => {
                const generation = turn.generation;
                const structured = turn.assistant?.structured_content ?? null;
                const insufficient =
                  generation?.answer_status === 'insufficient_evidence' || structured?.answer_status === 'insufficient_evidence';
                return (
                  <section key={turn.user.id} data-turn={index} aria-label={`${index + 1}. soru`} className="flex flex-col gap-5">
                    <div className="max-w-[500px] self-end whitespace-pre-wrap rounded-[14px] bg-muted px-4 py-2.5 text-[14.5px] leading-normal">
                      {turn.user.content}
                    </div>
                    {generation && isActive(generation) && (
                      <GenerationProgress generation={generation} cancelling={cancelling} onCancel={() => void cancel(generation.id)} />
                    )}
                    {generation?.status === 'completed' && insufficient && (
                      <InsufficientCard reason={structured?.limitations[0] ?? null} onEdit={() => setDraft(turn.user.content)} />
                    )}
                    {generation?.status === 'completed' && !insufficient && structured && turn.rendered && (
                      <AnswerView
                        answer={structured}
                        rendered={turn.rendered}
                        generation={generation}
                        selectedSourceId={selected?.messageId === turn.assistant?.id ? selected?.sourceId ?? null : null}
                        onSelectSource={(sourceId) => turn.assistant && setSelected({ messageId: turn.assistant.id, sourceId })}
                      />
                    )}
                    {generation?.status === 'completed' && !insufficient && !structured && turn.assistant && (
                      <p className="m-0 whitespace-pre-wrap text-[15px] leading-relaxed">{turn.assistant.content}</p>
                    )}
                    {generation?.status === 'failed' && (
                      <FailedCard code={generation.safe_error_code} onRetry={() => void send(turn.user.content)} />
                    )}
                    {generation?.status === 'cancelled' && <CancelledCard onResend={() => void send(turn.user.content)} />}
                  </section>
                );
              })}
            </div>
          </div>
          {turns.length >= 2 && (
            <PromptRail
              prompts={turns.map((turn) => ({ text: turn.user.content, time: timeFormatter.format(new Date(turn.user.created_at)) }))}
              activeIndex={activePrompt}
              onJump={jumpTo}
            />
          )}
        </div>

        <div className="shrink-0 px-4 pb-4 pt-3 sm:px-6">
          <div className="mx-auto flex max-w-[640px] flex-col gap-2">
            {actionError && (
              <p role="alert" className="m-0 rounded-[10px] border border-err-line bg-err-bg px-3.5 py-2.5 text-[13px] text-err">
                {actionError}
              </p>
            )}
            <Composer
              variant="compact"
              value={draft}
              onChange={setDraft}
              onSubmit={() => void send(draft)}
              includeDoctrine={includeDoctrine}
              onDoctrineChange={changeDoctrine}
              busy={sending}
              placeholder="Takip sorusu sorun…"
            />
            <p className="m-0 text-center text-[11.5px] text-fg3">BekenAI hukuki danışmanlık yerine geçmez.</p>
          </div>
        </div>
      </div>

      {selectedSource && selectedTurn?.rendered && (
        <>
          <aside aria-label="Kaynak paneli" className="hidden w-[440px] shrink-0 border-l border-line bg-surface lg:flex lg:flex-col">
            <SourcePanel
              selected={selectedSource}
              sources={selectedTurn.rendered.sources}
              onSelect={(sourceId) => setSelected((current) => (current ? { ...current, sourceId } : current))}
              onClose={() => setSelected(null)}
            />
          </aside>
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Kaynak">
            <button type="button" aria-label="Kaynak panelini kapat" className="absolute inset-0 bg-[var(--scrim)]" onClick={() => setSelected(null)} />
            <div className="absolute inset-x-0 bottom-0 flex max-h-[85dvh] flex-col overflow-hidden rounded-t-[20px] bg-surface shadow-lg">
              <span aria-hidden="true" className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-line-strong" />
              <SourcePanel
                selected={selectedSource}
                sources={selectedTurn.rendered.sources}
                onSelect={(sourceId) => setSelected((current) => (current ? { ...current, sourceId } : current))}
                onClose={() => setSelected(null)}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
