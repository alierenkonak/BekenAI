'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Icon } from '@/components/icons';
import { api } from '@/lib/api';
import { describeError } from '@/lib/format';
import type { LegalCase } from '@/lib/types';
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
  const [error, setError] = useState<string | null>(null);

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
            busy={sending}
            autoFocus
            placeholder="Örneğin: İşveren ihbar süresine uymadan sözleşmemi feshetti. Hangi alacaklarımı talep edebilirim?"
            extra={caseSelect}
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

          <div className="flex items-start justify-center gap-2 text-center text-[12.5px] text-fg3">
            <Icon name="book" size={14} className="mt-0.5" />
            <span>Kapsam: iş hukukuna ilişkin kanunlar · Yargıtay kararları · doktrin</span>
          </div>
        </div>
      </div>

      <p className="m-0 px-6 pb-[18px] text-center text-xs text-fg3">
        BekenAI hukuki danışmanlık yerine geçmez. Cevaplar yalnızca doğrulanabilen kaynaklara dayanır.
      </p>
    </div>
  );
}
