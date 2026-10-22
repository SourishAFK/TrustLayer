import { describe, expect, it } from 'vitest';
import { segments, type Claim } from './report';

const claim = (claim_id: string, start: number, end: number) => ({ claim_id, text_span: { start, end } }) as Claim;

describe('segments', () => {
  it('cuts by code points, so emoji and € before a claim do not shift it', () => {
    const text = '😀 Pay €90. Done.';
    const parts = segments(text, [claim('c1', 2, 10)]);
    expect(parts.map(p => p.text)).toEqual(['😀 ', 'Pay €90.', ' Done.']);
    expect(parts[1].claim?.claim_id).toBe('c1');
  });

  it('skips overlapping or out-of-range spans instead of garbling the text', () => {
    const parts = segments('abcdef', [claim('a', 0, 3), claim('b', 2, 4), claim('c', 5, 99)]);
    expect(parts.map(p => p.text).join('')).toBe('abcdef');
    expect(parts.filter(p => p.claim).map(p => p.claim!.claim_id)).toEqual(['a']);
  });
});
