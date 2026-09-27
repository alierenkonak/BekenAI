'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Icon } from '@/components/icons';
import { api } from '@/lib/api';
import { SAMPLE_FILE_URL, SAMPLE_QUESTIONS, mediaTypeOf, uploadProblem } from '@/lib/files';
import { describeError } from '@/lib/format';
import type { LegalCase } from '@/lib/types';
import { AttachButton, saveDraftHandoff } from './chat-files';
import { Composer } from './composer';
import { useConversations } from './conversations';

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
  const [includeDoctrine, setIncludeDoctrine] = useState(false);
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
    try {
      const queued = await api.sendChat(
        { message, include_doctrine: includeDoctrine, case_id: caseId || null },
        crypto.randomUUID(),
      );
      refresh();
      router.push(`/sohbet/${queued.conversation_id}`);
    } catch (sendError) {
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
        const created = await api.createConversation({ title, case_id: caseId || null, include_doctrine: includeDoctrine });
        conversationId = created.id;
        setAttachedConversationId(conversationId);
      }
      const targetId = conversationId;
      await Promise.all(
        files.map((file) => api.uploadConversationFile(targetId, file, mediaTypeOf(file) ?? 'application/pdf')),
      );
      saveDraftHandoff(targetId, draft);
      refresh();
      router.push(`/sohbet/${targetId}`);
    } catch (attachError) {
      setError(describeError(attachError));
      setAttaching(false);
    }
  };

  const caseSelect = (
    <label className="flex h-8 items-center gap-1.5 rounded-lg border border-dashed border-line-strong pl-2.5 pr-1 text-[13px] text-fg2">
      <Icon name="cases" size={15} />
      <span className="sr-only">Davaya bağla</span>
      <select
        value={caseId}
        onChange={(event) => setCaseId(event.target.value)}
        className="max-w-[180px] cursor-pointer truncate border-0 bg-transparent py-1 text-[13px] text-fg2 outline-none"
      >
        <option value="">Davaya bağla</option>
        {cases.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <header className="hidden h-14 shrink-0 items-center justify-between px-6 lg:flex">
        <span className="text-sm text-fg2">Yeni sohbet</span>
        <span className="flex items-center gap-1.5 text-[12.5px] text-fg3">
          <span className="size-[7px] rounded-full bg-ok" />
          İş hukuku kaynak dizini
        </span>
      </header>

      <div className="flex grow flex-col items-center px-4 pb-6 pt-12 sm:px-6 lg:pt-[104px]">
        <div className="flex w-full max-w-[720px] flex-col gap-7">
          <div className="flex flex-col items-center gap-3 text-center">
            <h1 className="m-0 font-serif text-[38px] font-normal leading-[1.05] tracking-[-0.01em] sm:text-5xl">
              Hangi konuyu araştırıyorsunuz?
            </h1>
            <p className="m-0 max-w-[560px] text-[15px] leading-relaxed text-fg2">
              Mevzuat ve Yargıtay kararlarına dayanan cevaplar alın. Her iddia, kaynak pasajıyla karşılaştırılarak doğrulanır.
            </p>
          </div>

          <Composer
            variant="hero"
            value={draft}
            onChange={setDraft}
            onSubmit={() => void send(draft)}
            includeDoctrine={includeDoctrine}
            onDoctrineChange={setIncludeDoctrine}
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
