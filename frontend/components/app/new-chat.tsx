'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { Icon } from '@/components/icons';
import { ApiError, api } from '@/lib/api';
import { SAMPLE_FILE_URL, SAMPLE_QUESTIONS, mediaTypeOf, uploadProblem } from '@/lib/files';
import { describeError } from '@/lib/format';
import type { LegalCase } from '@/lib/types';
import { rememberWebSearch, useWebSearchAvailable } from '@/lib/web-search';
import { AttachButton, saveDraftHandoff } from './chat-files';
import { Composer } from './composer';
import { useConversations } from './conversations';
import { Popover, moveFocus } from './popover';

// Drawn from the labour-law evaluation set so suggestions exercise real coverage.
const SUGGESTIONS = [
  { topic: 'Fesih', question: 'Savunmam alınmadan davranışım nedeniyle işten çıkarılabilir miyim?' },
  { topic: 'İşe iade', question: 'İşe iade için arabulucuya kaç gün içinde başvurmalıyım?' },
  { topic: 'Kıdem tazminatı', question: 'Kıdem tazminatı hesabında hangi ödemeler giydirilmiş ücrete eklenir?' },
  { topic: 'Fazla çalışma', question: 'İmzalı bordro fazla mesai alacağını engeller mi?' },
];

export function NewChat() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refresh } = useConversations();
  const [draft, setDraft] = useState(() => searchParams.get('q') ?? '');
  const webSearchAvailable = useWebSearchAvailable();
  const [webSearch, setWebSearch] = useState(false);
  const [deepResearch, setDeepResearch] = useState(false);
  const withWeb = webSearchAvailable && webSearch;
  const [caseId, setCaseId] = useState(() => searchParams.get('dava') ?? '');
  const [cases, setCases] = useState<LegalCase[]>([]);
  const [sending, setSending] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Reused if an upload fails, so a retry does not leave a trail of empty chats.
  const [attachedConversationId, setAttachedConversationId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .listCases()
      .then((page) => {
        if (active) setCases(page.items);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const send = async (text: string) => {
    const message = text.trim();
    if (message.length < 3 || sending) return;
    setSending(true);
    setError(null);
    const searchMode = withWeb ? 'web' : 'corpus';
    // After a partly failed upload the files that made it already sit in the chat created
    // for them; the question goes there, not to a new chat without them.
    const target = attachedConversationId;
    try {
      const queued = await api.sendChat(
        target
          ? { conversation_id: target, message, search_mode: searchMode, deep_research: deepResearch }
          : {
              message,
              case_id: caseId || null,
              search_mode: searchMode,
              deep_research: deepResearch,
            },
        crypto.randomUUID(),
      );
      // The switch stays on for the rest of this chat.
      if (withWeb) rememberWebSearch(queued.conversation_id, true);
      refresh();
      router.push(`/sohbet/${queued.conversation_id}`);
    } catch (sendError) {
      // Its files are still being processed: continue in that chat, where progress shows
      // and the question waits in the composer.
      if (target && sendError instanceof ApiError && sendError.code === 'files_processing') {
        saveDraftHandoff(target, message);
        if (withWeb) rememberWebSearch(target, true);
        refresh();
        router.push(`/sohbet/${target}`);
        return;
      }
      setError(describeError(sendError));
      setSending(false);
    }
  };

  // Files belong to a chat, so attaching one opens the chat first and continues there.
  const attach = async (files: File[]) => {
    if (!files.length || attaching || sending) return;
    const problem = files.map(uploadProblem).find(Boolean);
    if (problem) {
      setError(problem);
      return;
    }
    setAttaching(true);
    setError(null);
    try {
      let conversationId = attachedConversationId;
      if (!conversationId) {
        const title = draft.trim().replace(/\s+/g, ' ').slice(0, 80) || files[0].name.slice(0, 160);
        const created = await api.createConversation({ title, case_id: caseId || null });
        conversationId = created.id;
        setAttachedConversationId(conversationId);
      }
      const targetId = conversationId;
      await Promise.all(
        files.map((file) => api.uploadConversationFile(targetId, file, mediaTypeOf(file) ?? 'application/pdf')),
      );
      saveDraftHandoff(targetId, draft);
      if (withWeb) rememberWebSearch(targetId, true);
      refresh();
      router.push(`/sohbet/${targetId}`);
    } catch (attachError) {
      setError(describeError(attachError));
      setAttaching(false);
    }
  };

  const caseSelect = <CaseSelect cases={cases} value={caseId} onChange={setCaseId} />;

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <header className="hidden h-14 shrink-0 items-center px-6 lg:flex">
        <span className="text-sm text-fg2">Yeni sohbet</span>
      </header>

      <div className="flex grow flex-col items-center px-4 pb-6 pt-12 sm:px-6 lg:pt-[104px]">
        <div className="flex w-full max-w-[720px] flex-col gap-7">
          <div className="flex flex-col items-center gap-3 text-center">
            <h1 className="m-0 font-serif text-[38px] font-normal leading-[1.05] tracking-[-0.01em] sm:text-5xl">
              Hangi konuyu araştırıyorsunuz?
            </h1>
            <p className="m-0 max-w-[560px] text-[15px] leading-relaxed text-fg2">
              Mevzuat, Yargıtay kararları ve doktrine dayanan cevaplar alın. Her iddia, kaynak pasajıyla karşılaştırılarak doğrulanır.
            </p>
          </div>

          <Composer
            variant="hero"
            value={draft}
            onChange={setDraft}
            onSubmit={() => void send(draft)}
            webSearch={webSearchAvailable ? { checked: webSearch, onChange: setWebSearch } : undefined}
            deepResearch={{ checked: deepResearch, onChange: setDeepResearch }}
            busy={sending || attaching}
            autoFocus
            placeholder="Örneğin: İşveren ihbar süresine uymadan sözleşmemi feshetti. Hangi alacaklarımı talep edebilirim?"
            locked={attaching ? 'Dosya yükleniyor; ardından sohbete geçeceksiniz…' : null}
            extra={
              <>
                {caseSelect}
                <AttachButton onFiles={(files) => void attach(files)} disabled={attaching || sending} />
              </>
            }
          />
          {error && (
            <p role="alert" className="m-0 rounded-[10px] border border-err-line bg-err-bg px-3.5 py-2.5 text-[13px] text-err">
              {error}
            </p>
          )}

          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {SUGGESTIONS.map((item) => (
              <button
                key={item.question}
                type="button"
                disabled={sending}
                onClick={() => void send(item.question)}
                className="flex flex-col gap-1.5 rounded-xl border border-line bg-surface px-4 py-3.5 text-left transition-colors hover:border-line-strong hover:bg-hover disabled:opacity-60"
              >
                <span className="text-xs font-medium text-fg3">{item.topic}</span>
                <span className="text-sm leading-snug text-fg">{item.question}</span>
              </button>
            ))}
          </div>

          <section aria-labelledby="sample-file" className="flex flex-col gap-3 rounded-xl border border-dashed border-file-line bg-file-bg/40 px-4 py-3.5">
            <div className="flex flex-wrap items-center gap-2">
              <Icon name="file" size={16} className="text-file" />
              <h2 id="sample-file" className="m-0 text-[13.5px] font-semibold">
                Kendi dosyanızla deneyin
              </h2>
              <span className="grow" />
              <a
                href={SAMPLE_FILE_URL}
                download
                className="flex h-8 items-center gap-1.5 rounded-lg border border-file-line bg-surface px-3 text-[13px] font-medium text-file no-underline hover:bg-hover"
              >
                <Icon name="download" size={14} />
                Örnek dava dosyası (PDF)
              </a>
            </div>
            <p className="m-0 text-[13px] leading-normal text-fg2">
              Ataç simgesiyle bir dilekçe, fesih bildirimi ya da karar ekleyin; cevaplar dosyadaki sayfaya atıf yapar. Elinizde dosya
              yoksa kurgusal örneği indirip ekleyin, ardından şunları sorun:
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SAMPLE_QUESTIONS.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => setDraft(question)}
                  className="rounded-full border border-line bg-surface px-3 py-1 text-left text-[12.5px] text-fg2 hover:border-line-strong hover:text-fg"
                >
                  {question}
                </button>
              ))}
            </div>
          </section>

          <div className="flex items-start justify-center gap-2 text-center text-[12.5px] text-fg3">
            <Icon name="book" size={14} className="mt-0.5" />
            <span>Kapsam: iş hukukuna ilişkin kanunlar · Yargıtay kararları · doktrin · yüklediğiniz dosyalar</span>
          </div>
        </div>
      </div>

      <p className="m-0 px-6 pb-[18px] text-center text-xs text-fg3">
        BekenAI hukuki danışmanlık yerine geçmez. Cevaplar yalnızca doğrulanabilen kaynaklara dayanır.
      </p>
    </div>
  );
}

/** Picks the case a new chat belongs to; the case's files are then searched in the chat too. */
function CaseSelect({ cases, value, onChange }: { cases: LegalCase[]; value: string; onChange: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const selected = cases.find((item) => item.id === value) ?? null;

  useEffect(() => {
    if (!open) return;
    window.requestAnimationFrame(() =>
      (listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]') ?? listRef.current?.querySelector<HTMLElement>('[role="option"]'))?.focus(),
    );
  }, [open]);

  const choose = (id: string) => {
    onChange(id);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const option = (id: string, label: string, detail: string | null) => {
    const active = id === value;
    return (
      <button
        key={id || 'none'}
        type="button"
        role="option"
        aria-selected={active}
        onClick={() => choose(id)}
        className="flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left outline-none hover:bg-hover focus-visible:bg-hover"
      >
        <span className="flex min-w-0 grow flex-col gap-0.5">
          <span className={`truncate text-[13px] ${active ? 'font-semibold text-fg' : 'font-medium text-fg'}`}>{label}</span>
          {detail && <span className="truncate text-xs text-fg3">{detail}</span>}
        </span>
        <Icon name="check" size={14} strokeWidth={2.2} className={`mt-0.5 shrink-0 text-accent ${active ? '' : 'invisible'}`} />
      </button>
    );
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={selected ? `Bağlı dava: ${selected.name}` : 'Davaya bağla'}
        onClick={() => setOpen((current) => !current)}
        className={`flex h-8 max-w-[220px] items-center gap-1.5 rounded-lg border px-2.5 text-[13px] transition-colors ${
          selected ? 'border-file-line bg-file-bg font-medium text-file' : 'border-dashed border-line-strong text-fg2 hover:bg-hover hover:text-fg'
        }`}
      >
        <Icon name="cases" size={15} className="shrink-0" />
        <span className="truncate">{selected ? selected.name : 'Davaya bağla'}</span>
        <Icon name="chevDown" size={13} className={`shrink-0 opacity-70 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={triggerRef} placement="bottom-start" className="w-[300px]">
        <div ref={listRef} role="listbox" aria-label="Dava" onKeyDown={(event) => moveFocus(event, '[role="option"]')} className="flex flex-col">
          <p className="m-0 px-2.5 pb-1.5 pt-1 text-xs leading-snug text-fg3">Bağlanan davanın dosyaları bu sohbette de aranır.</p>
          {option('', 'Davaya bağlama', 'Sohbet hiçbir davaya ait olmaz')}
          {cases.length > 0 && <div className="mx-2.5 my-1 h-px bg-line" />}
          <div className="flex max-h-[240px] flex-col overflow-y-auto">
            {cases.map((item) => option(item.id, item.name, item.description))}
          </div>
          <div className="mx-2.5 my-1 h-px bg-line" />
          <Link
            href="/davalar"
            className="flex h-8 items-center gap-2 rounded-lg px-2.5 text-[13px] text-fg2 no-underline hover:bg-hover hover:text-fg"
          >
            <Icon name="plus" size={14} />
            Yeni dava oluştur
          </Link>
        </div>
      </Popover>
    </>
  );
}
