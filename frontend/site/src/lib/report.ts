import type { Verdict } from './content';

// The parts of the API's VerificationReport (schema 2.0) that the site displays.
export type Evidence = {
  evidence_id: string; stance: 'supports' | 'contradicts'; url: string; title: string | null; publisher: string | null;
  domain: string; source_type: string; retrieval: string; published_at: string | null; passage: string; quote: string;
  rationale: string | null;
};
export type Calculation = { kind: string; expression: string; stated_value: string; computed_value: string; consistent: boolean; note: string };
export type Claim = {
  claim_id: string; exact_text: string; text_span: { start: number; end: number }; claim_type: string;
  verification_status: Verdict; evidence: Evidence[]; contradictions: Evidence[]; calculations: Calculation[];
  explanation: string; limitations: string[]; suggested_correction: string | null; missing_evidence: string[];
};
export type Citation = {
  citation_id: string; raw_text: string; url: string | null; doi: string | null; status: string;
  http_status: number | null; title: string | null; quote_check: string; explanation: string;
};
export type Signal = { signal_id: string; engine: string; kind: string; severity: 'info' | 'warning' | 'critical'; text: string; explanation: string };
export type Report = {
  report_id: string; mode: string; status: 'completed' | 'partial' | 'failed'; response_text: string;
  original_question: string | null; claims: Claim[]; citations: Citation[]; signals: Signal[];
  completeness: { status: string; missing: { kind: string; description: string }[]; note: string };
  summary: { total_extracted: number; supported: number; contradicted: number; disputed: number; unverified: number; not_checkable: number };
  limitations: string[]; incomplete_checks: string[];
  usage: { duration_ms: number; model_calls: number; search_calls: number; pages_fetched: number; estimated_cost_usd: number };
  privacy: { stored: boolean; web_search_used: boolean; documents_sent_to_ai: boolean; ai_providers: string[]; search_providers: string[] };
};
export type Progress = { type: string; stage: string; status: string; message: string; claim_id: string | null; elapsed_ms: number };
export type StreamLine = { type: 'progress'; event: Progress } | { type: 'report'; report: Report } | { type: 'error'; message: string };

/** Splits the answer into plain text and claim pieces. Spans count Unicode code points, like the API. */
export function segments(text: string, claims: Claim[]) {
  const points = Array.from(text);
  const parts: { text: string; claim?: Claim }[] = [];
  let cursor = 0;
  for (const claim of [...claims].sort((a, b) => a.text_span.start - b.text_span.start)) {
    const { start, end } = claim.text_span;
    if (start < cursor || end > points.length) continue; // never trust a malformed span
    if (start > cursor) parts.push({ text: points.slice(cursor, start).join('') });
    parts.push({ text: points.slice(start, end).join(''), claim });
    cursor = end;
  }
  if (cursor < points.length) parts.push({ text: points.slice(cursor).join('') });
  return parts;
}

/** Plain-language names for the checks the engine runs, in pipeline order. */
export const STAGES: { key: string; label: string }[] = [
  { key: 'extraction', label: 'Split the answer into claims' },
  { key: 'numerical', label: 'Redo the math' },
  { key: 'consistency', label: 'Look for self-contradictions' },
  { key: 'uncertainty', label: 'Flag overconfident wording' },
  { key: 'planning', label: 'Decide what to research' },
  { key: 'evidence', label: 'Read sources and your documents' },
  { key: 'citations', label: 'Open every citation' },
  { key: 'market', label: 'Check market claims' },
  { key: 'sycophancy', label: 'Check for telling you what you want to hear' },
  { key: 'completeness', label: 'Check the whole question was answered' },
  { key: 'freshness', label: 'Check for out-of-date facts' },
];

export const CITATION_LABEL: Record<string, { label: string; tone: Verdict }> = {
  supports: { label: 'Supports the claim', tone: 'SUPPORTED' },
  does_not_support: { label: 'Does not support it', tone: 'CONTRADICTED' },
  contradicts: { label: 'Contradicts it', tone: 'CONTRADICTED' },
  accessible_unassessed: { label: 'Opens; not assessed', tone: 'UNVERIFIED' },
  inaccessible: { label: 'Could not be read', tone: 'UNVERIFIED' },
  broken: { label: 'Broken link', tone: 'CONTRADICTED' },
  invalid_or_fabricated: { label: 'Invalid or made up', tone: 'CONTRADICTED' },
  blocked: { label: 'Blocked for safety', tone: 'NOT CHECKABLE' },
  not_checked: { label: 'Not checked', tone: 'NOT CHECKABLE' },
};

export const SOURCE_KIND: Record<string, string> = {
  answer_key: 'Your answer key', user_provided: 'Your document', primary: 'Primary source', official: 'Official source',
  academic: 'Academic source', reference: 'Reference work', news: 'News', other: 'Other source',
};
