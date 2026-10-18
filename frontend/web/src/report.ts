import { z } from 'zod';

const span = z.object({ start: z.number().int().nonnegative(), end: z.number().int().positive() });
const claimSchema = z.object({
  claim_id: z.string().min(1), exact_text: z.string().min(1), text_span: span,
  claim_type: z.enum(['factual', 'numerical', 'logical', 'historical', 'time_sensitive', 'comparative', 'business_market', 'scientific', 'predictive', 'subjective_normative', 'negative_universal', 'not_independently_checkable']),
  context: z.string(), qualifiers: z.array(z.string()),
  scope: z.object({ dates: z.array(z.string()), geographical_scope: z.array(z.string()) }),
  objectively_checkable: z.boolean(), verification_status: z.enum(['UNVERIFIED', 'NOT CHECKABLE']),
  evidence: z.array(z.never()), contradictions: z.array(z.never()), explanation: z.string(),
  limitations: z.array(z.string()), suggested_correction: z.null(), checked_at: z.null(),
});
const reportSchema = z.object({
  schema_version: z.literal('1.0'), mode: z.enum(['quick', 'deep']), response_text: z.string(),
  original_question: z.string().nullable(), extraction_status: z.enum(['completed', 'partial', 'failed']),
  method: z.string(), extracted_at: z.string().datetime({ offset: true }), claims: z.array(claimSchema),
  summary: z.object({ total_extracted: z.number().int().nonnegative(), supported: z.literal(0), contradicted: z.literal(0),
    disputed: z.literal(0), unverified: z.number().int().nonnegative(), not_checkable: z.number().int().nonnegative(), investigated: z.literal(0) }),
  limitations: z.array(z.string()), incomplete_checks: z.array(z.string()),
  omitted_segments: z.array(z.object({ text_span: span, reason: z.string() })),
  usage: z.object({ duration_ms: z.number().nonnegative(), model_tokens: z.literal(0), search_calls: z.literal(0), estimated_cost_usd: z.literal(0) }),
});
export type Claim = z.infer<typeof claimSchema>;
export type Report = z.infer<typeof reportSchema>;

export function parseReport(value: unknown, source: string): Report {
  const report = reportSchema.parse(value);
  const points = Array.from(source);
  let last = 0;
  const ids = new Set<string>();
  if (report.response_text !== source) throw new Error('Response text mismatch');
  for (const claim of report.claims) {
    const { start, end } = claim.text_span;
    if (start < last || end <= start || end > points.length || ids.has(claim.claim_id)
      || points.slice(start, end).join('') !== claim.exact_text
      || !source.includes(claim.context) || !claim.context.includes(claim.exact_text)
      || claim.verification_status !== (claim.objectively_checkable ? 'UNVERIFIED' : 'NOT CHECKABLE')) {
      throw new Error('Invalid claim spans or status');
    }
    ids.add(claim.claim_id); last = end;
  }
  const unverified = report.claims.filter(c => c.objectively_checkable).length;
  if (report.summary.total_extracted !== report.claims.length || report.summary.unverified !== unverified
    || report.summary.not_checkable !== report.claims.length - unverified
    || (report.extraction_status === 'failed' && report.claims.length)) throw new Error('Invalid report summary');
  return report;
}

export function highlightParts(text: string, claims: Claim[]) {
  const points = Array.from(text);
  const parts: { text: string; claim?: Claim }[] = [];
  let cursor = 0;
  for (const claim of claims) {
    parts.push({ text: points.slice(cursor, claim.text_span.start).join('') });
    parts.push({ text: points.slice(claim.text_span.start, claim.text_span.end).join(''), claim });
    cursor = claim.text_span.end;
  }
  parts.push({ text: points.slice(cursor).join('') });
  return parts;
}

export function readableReport(report: Report) {
  return [
    'TRUSTLAYER — CLAIM EXTRACTION REPORT',
    'Extraction only. No independent factual verification has run.',
    `Extracted: ${report.extracted_at} | Mode: ${report.mode} | Method: ${report.method}`,
    `Execution: ${report.extraction_status} | Extracted claims: ${report.summary.total_extracted} | Investigated: 0`,
    'Counts do not establish verification coverage or a probability of truth.',
    '', 'ORIGINAL QUESTION', report.original_question || 'Not supplied', '', 'ORIGINAL RESPONSE', report.response_text,
    '', 'CLAIMS', ...report.claims.flatMap(c => [
      `${c.claim_id} · ${c.verification_status} · ${c.claim_type}`, c.exact_text,
      `Span: ${c.text_span.start}–${c.text_span.end} (Unicode code points)`, `Context: ${c.context}`,
      `Qualifiers: ${c.qualifiers.join(', ') || 'None identified'}`,
      `Dates: ${c.scope.dates.join(', ') || 'None identified'}; Geography: ${c.scope.geographical_scope.join(', ') || 'None identified'}`,
      c.explanation, ...c.limitations, 'Evidence: none retrieved. Checked at: not checked.', '',
    ]), 'LIMITATIONS', ...report.limitations, '', 'CHECKS NOT RUN', ...report.incomplete_checks,
    '', 'OMITTED SEGMENTS', ...report.omitted_segments.map(s => `${s.text_span.start}–${s.text_span.end}: ${s.reason}`),
    '', `Model tokens: 0 | Search calls: 0 | Estimated API cost: $0 | Extraction time: ${report.usage.duration_ms} ms`,
  ].join('\n');
}

export function downloadReport(report: Report, format: 'json' | 'txt') {
  const content = format === 'json' ? JSON.stringify(report, null, 2) : readableReport(report);
  const url = URL.createObjectURL(new Blob([content], { type: format === 'json' ? 'application/json' : 'text/plain;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `trustlayer-extraction.${format}`;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
