import { describe, expect, it } from 'vitest';
import { plainStage, segments, type Claim } from './report';

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

describe('plainStage', () => {
  it('turns engine messages into plain words', () => {
    expect(plainStage('numerical', 'completed', '1 calculation(s) checked, 1 inconsistent.')).toBe('1 sum redone, 1 wrong');
    expect(plainStage('sycophancy', 'completed', '0 lexical signal(s); no behavioral score (no original question).')).toBe('Wording checked');
    expect(plainStage('uncertainty', 'completed', 'Examined 3 claim(s): 0 absolute-language phrase(s), 0 overconfident prediction(s), 0 missing caveat(s).'))
      .toBe('No overconfident wording');
    expect(plainStage('completeness', 'completed', '1 sub-question(s); 1 possible omission(s).')).toBe('1 part of the question may be unanswered');
    expect(plainStage('evidence', 'started', 'Reading wikipedia.org')).toBe('Reading wikipedia.org');
    expect(plainStage('citations', 'started', 'Checking citation r2')).toBe('Opening a citation…');
  });

  it('never shows raw engine text, even for a message it does not know', () => {
    expect(plainStage('evidence', 'completed', 'Some new engine detail(s)')).toBe('');
    expect(plainStage('market', 'skipped', 'No market or competitor claims to investigate.')).toBe('');
  });
});
