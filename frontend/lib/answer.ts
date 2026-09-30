import type {
  AnswerBlock,
  Citation,
  ConversationalAnswer,
  LegacyAnswer,
  SourceChannel,
  SourceSnapshot,
  StructuredAnswer,
  TemporalCheck,
} from './types';

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

export interface Chip {
  sourceId: string;
  label: string;
  channel: SourceChannel;
  partial: boolean;
  /** The provision changed after the case date (see the Yürürlük kontrolü). */
  changed?: boolean;
}

export interface RenderedClaim {
  number: number;
  text: string;
  chips: Chip[];
}

export interface RenderedSentence extends RenderedClaim {
  unverified: boolean;
}

export interface RenderedBlock {
  kind: AnswerBlock['kind'];
  sentences: RenderedSentence[];
}

/** Answers from before the conversational format: one claim list per source kind. */
export interface RenderedLegacyAnswer {
  kind: 'legacy';
  file: RenderedClaim[];
  primary: RenderedClaim[];
  doctrine: RenderedClaim[];
  sources: SourceRef[];
}

export interface RenderedTemporalCheck {
  sourceId: string;
  /** The cited source's chip label; null if the source is not shown. */
  label: string | null;
  level: TemporalCheck['level'];
  text: string;
}

export interface RenderedConversation {
  kind: 'conversational';
  blocks: RenderedBlock[];
  /** The labelled web section after the answer; empty without web search. */
  webBlocks: RenderedBlock[];
  sources: SourceRef[];
  unverifiedCount: number;
  temporalChecks: RenderedTemporalCheck[];
}

export type RenderedAnswer = RenderedLegacyAnswer | RenderedConversation;

const LABEL_PREFIX: Record<SourceChannel, string> = { primary: '', doctrine: 'D', file: 'F', web: 'W' };

export function isConversational(answer: StructuredAnswer): answer is ConversationalAnswer {
  return answer.format === 'conversational-v1';
}

/**
 * Numbers sources by first appearance per channel (file F1, F2…; primary 1, 2…;
 * doctrine D1, D2…; web W1, W2…) and joins each sentence–source pair to its persisted citation so
 * chips carry the verifier's verdict.
 */
function createNumbering(citations: Citation[]) {
  const citationByPair = new Map(citations.map((citation) => [`${citation.claim_id}::${citation.source_id}`, citation]));
  const sources = new Map<string, SourceRef>();
  const counts: Record<SourceChannel, number> = { primary: 0, doctrine: 0, file: 0, web: 0 };

  const chipsFor = (claimId: string, number: number, text: string, sourceIds: string[]): Chip[] => {
    const chips: Chip[] = [];
    for (const sourceId of sourceIds) {
      const citation = citationByPair.get(`${claimId}::${sourceId}`);
      if (!citation) continue;
      let ref = sources.get(sourceId);
      if (!ref) {
        const channel = citation.source_channel;
        counts[channel] += 1;
        ref = { sourceId, label: `${LABEL_PREFIX[channel]}${counts[channel]}`, channel, snapshot: citation.source_snapshot, claims: [] };
        sources.set(sourceId, ref);
      }
      ref.claims.push({ number, text, status: citation.support_status, reason: citation.support_reason });
      chips.push({ sourceId, label: ref.label, channel: ref.channel, partial: citation.support_status === 'partial' });
    }
    return chips;
  };
  return { chipsFor, sources: () => [...sources.values()] };
}

export function renderAnswer(answer: StructuredAnswer, citations: Citation[]): RenderedAnswer {
  return isConversational(answer) ? renderConversation(answer, citations) : renderLegacy(answer, citations);
}

function renderConversation(answer: ConversationalAnswer, citations: Citation[]): RenderedConversation {
  const { chipsFor, sources } = createNumbering(citations);
  const checks = answer.temporal_checks ?? [];
  const changed = new Set(checks.filter((check) => check.level === 'changed_after').map((check) => check.source_id));
  let number = 0;
  const render = (items: AnswerBlock[]): RenderedBlock[] =>
    items.map((block) => ({
      kind: block.kind,
      sentences: block.sentences.map((sentence) => {
        number += 1;
        return {
          number,
          text: sentence.text,
          chips: chipsFor(sentence.id, number, sentence.text, sentence.source_ids).map((chip) =>
            changed.has(chip.sourceId) ? { ...chip, changed: true } : chip,
          ),
          unverified: sentence.verification === 'unverified',
        };
      }),
    }));
  // Numbered in reading order: the answer first, then the web section.
  const blocks = render(answer.blocks);
  const webBlocks = render(answer.web_blocks ?? []);
  const refs = sources();
  const labels = new Map(refs.map((ref) => [ref.sourceId, ref.label]));
  return {
    kind: 'conversational',
    blocks,
    webBlocks,
    sources: refs,
    unverifiedCount: answer.unverified_count ?? 0,
    temporalChecks: checks.map((check) => ({
      sourceId: check.source_id,
      label: labels.get(check.source_id) ?? null,
      level: check.level,
      text: check.text,
    })),
  };
}

function renderLegacy(answer: LegacyAnswer, citations: Citation[]): RenderedLegacyAnswer {
  const { chipsFor, sources } = createNumbering(citations);
  let claimNumber = 0;
  const renderSection = (section: LegacyAnswer['primary_answer']): RenderedClaim[] =>
    (section?.claims ?? []).map((claim) => {
      claimNumber += 1;
      return { number: claimNumber, text: claim.text, chips: chipsFor(claim.claim_id, claimNumber, claim.text, claim.source_ids) };
    });
  // Facts from the user's file come first, then the law they are weighed against.
  const file = renderSection(answer.file_answer ?? null);
  const primary = renderSection(answer.primary_answer);
  const doctrine = renderSection(answer.doctrine_answer);
  return { kind: 'legacy', file, primary, doctrine, sources: sources() };
}

export function sourceKind(snapshot: SourceSnapshot, channel: SourceChannel): string {
  if (channel === 'web') return 'Web';
  if (channel === 'file') return 'Dosya';
  if (channel === 'doctrine') return 'Doktrin';
  return snapshot.decision_metadata.case_number || snapshot.decision_metadata.decision_number ? 'İçtihat' : 'Mevzuat';
}

export function sourceSubtitle(snapshot: SourceSnapshot): string {
  if (snapshot.source_scope === 'private') {
    return [snapshot.location_label, snapshot.section_title].filter(Boolean).join(' · ');
  }
  if (snapshot.source_scope === 'web') {
    const published = snapshot.published_date ? new Date(snapshot.published_date).toLocaleDateString('tr-TR') : null;
    return [snapshot.site, published].filter(Boolean).join(' · ');
  }
  const decision = snapshot.decision_metadata;
  const parts: string[] = [];
  if (decision.case_number) parts.push(`E. ${decision.case_number}`);
  if (decision.decision_number) parts.push(`K. ${decision.decision_number}`);
  if (parts.length === 0 && snapshot.breadcrumb.length) parts.push(snapshot.breadcrumb[snapshot.breadcrumb.length - 1]);
  if (decision.document_date) parts.push(new Date(decision.document_date).toLocaleDateString('tr-TR'));
  return parts.join(' · ');
}
