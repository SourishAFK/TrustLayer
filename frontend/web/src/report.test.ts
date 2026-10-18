import { describe, expect, it } from 'vitest';
import { highlightParts, parseReport, readableReport } from './report';

const source = '🚀 Acme has 10 staff.';
const fixture = () => ({
  schema_version: '1.0', mode: 'quick', response_text: source, original_question: null,
  extraction_status: 'completed', method: 'rules-v1', extracted_at: '2026-10-10T12:00:00Z',
  claims: [{ claim_id: 'c1', exact_text: 'Acme has 10 staff', text_span: { start: 2, end: 19 },
    claim_type: 'numerical', context: source, qualifiers: [], scope: { dates: [], geographical_scope: [] },
    objectively_checkable: true, verification_status: 'UNVERIFIED', evidence: [], contradictions: [],
    explanation: 'No evidence retrieved.', limitations: [], suggested_correction: null, checked_at: null }],
  summary: { total_extracted: 1, supported: 0, contradicted: 0, disputed: 0, unverified: 1, not_checkable: 0, investigated: 0 },
  limitations: ['Rule baseline.'], incomplete_checks: ['Evidence retrieval has not run.'], omitted_segments: [],
  usage: { duration_ms: 2, model_tokens: 0, search_calls: 0, estimated_cost_usd: 0 },
});

describe('report trust boundary', () => {
  it('handles Unicode code point spans without splitting emoji', () => {
    const report = parseReport(fixture(), source);
    const parts = highlightParts(source, report.claims);
    expect(parts.map(p => p.text)).toEqual(['🚀 ', 'Acme has 10 staff', '.']);
    expect(parts.map(p => p.text).join('')).toBe(source);
  });
  it('rejects out of bounds or mismatched spans', () => {
    const data = fixture(); data.claims[0].text_span.end = 100;
    expect(() => parseReport(data, source)).toThrow();
  });
  it('rejects a report for another input', () => {
    expect(() => parseReport(fixture(), 'Different source')).toThrow();
  });
  it('rejects premature support or invented evidence', () => {
    const data = fixture(); data.claims[0].verification_status = 'SUPPORTED';
    expect(() => parseReport(data, source)).toThrow();
    expect(() => parseReport({ ...fixture(), claims: [{ ...fixture().claims[0], evidence: [{ url: 'https://example.org' }] }] }, source)).toThrow();
  });
  it('rejects contradictory summary counts', () => {
    const data = fixture(); data.summary.total_extracted = 5;
    expect(() => parseReport(data, source)).toThrow();
  });
  it('rejects duplicate claims', () => {
    const data = fixture(); data.claims.push(data.claims[0]);
    expect(() => parseReport(data, source)).toThrow();
  });
  it('preserves limits and source in readable export', () => {
    const result = readableReport(parseReport(fixture(), source));
    expect(result).toContain(source);
    expect(result).toContain('Evidence retrieval has not run.');
    expect(result).toContain('UNVERIFIED');
    expect(result).toContain('not establish verification coverage');
  });
});
