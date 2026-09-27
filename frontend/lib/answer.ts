import type { Citation, SourceChannel, SourceSnapshot, StructuredAnswer } from './types';

export interface SourceClaim {
  number: number;
  text: string;
  status: 'supported' | 'partial';
  reason: string | null;
}

export interface SourceRef {
  sourceId: string;
  label: string;
  channel: SourceChannel;
  snapshot: SourceSnapshot;
  claims: SourceClaim[];
}

export interface RenderedClaim {
  number: number;
  text: string;
  chips: { sourceId: string; label: string; channel: SourceChannel; partial: boolean }[];
}

export interface RenderedAnswer {
  file: RenderedClaim[];
  primary: RenderedClaim[];
  doctrine: RenderedClaim[];
  sources: SourceRef[];
}

const LABEL_PREFIX: Record<SourceChannel, string> = { primary: '', doctrine: 'D', file: 'F' };

/**
 * Numbers sources by first appearance per channel (file F1, F2…; primary 1, 2…;
 * doctrine D1, D2…) and joins each claim–source pair to its persisted citation so
 * chips carry the verifier's verdict.
 */
export function renderAnswer(answer: StructuredAnswer, citations: Citation[]): RenderedAnswer {
  const citationByPair = new Map(citations.map((citation) => [`${citation.claim_id}::${citation.source_id}`, citation]));
  const sources = new Map<string, SourceRef>();
  const counts: Record<SourceChannel, number> = { primary: 0, doctrine: 0, file: 0 };
  let claimNumber = 0;

  const renderSection = (claims: StructuredAnswer['primary_answer']): RenderedClaim[] =>
    (claims?.claims ?? []).map((claim) => {
      claimNumber += 1;
      const number = claimNumber;
      const chips: RenderedClaim['chips'] = [];
      for (const sourceId of claim.source_ids) {
        const citation = citationByPair.get(`${claim.claim_id}::${sourceId}`);
        if (!citation) continue;
        let ref = sources.get(sourceId);
        if (!ref) {
          const channel = citation.source_channel;
          counts[channel] += 1;
          ref = {
            sourceId,
            label: `${LABEL_PREFIX[channel]}${counts[channel]}`,
            channel,
            snapshot: citation.source_snapshot,
            claims: [],
          };
          sources.set(sourceId, ref);
        }
        ref.claims.push({ number, text: claim.text, status: citation.support_status, reason: citation.support_reason });
        chips.push({ sourceId, label: ref.label, channel: ref.channel, partial: citation.support_status === 'partial' });
      }
      return { number, text: claim.text, chips };
    });

  // Facts from the user's file come first, then the law they are weighed against.
  const file = renderSection(answer.file_answer ?? null);
  const primary = renderSection(answer.primary_answer);
  const doctrine = renderSection(answer.doctrine_answer);
  return { file, primary, doctrine, sources: [...sources.values()] };
}

export function sourceKind(snapshot: SourceSnapshot, channel: SourceChannel): string {
  if (channel === 'file') return 'Dosya';
  if (channel === 'doctrine') return 'Doktrin';
  return snapshot.decision_metadata.case_number || snapshot.decision_metadata.decision_number ? 'İçtihat' : 'Mevzuat';
}

export function sourceSubtitle(snapshot: SourceSnapshot): string {
  if (snapshot.source_scope === 'private') {
    return [snapshot.location_label, snapshot.section_title].filter(Boolean).join(' · ');
  }
  const decision = snapshot.decision_metadata;
  const parts: string[] = [];
  if (decision.case_number) parts.push(`E. ${decision.case_number}`);
  if (decision.decision_number) parts.push(`K. ${decision.decision_number}`);
  if (parts.length === 0 && snapshot.breadcrumb.length) parts.push(snapshot.breadcrumb[snapshot.breadcrumb.length - 1]);
  if (decision.document_date) parts.push(new Date(decision.document_date).toLocaleDateString('tr-TR'));
  return parts.join(' · ');
}
