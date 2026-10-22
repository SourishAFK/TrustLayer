import { describe, expect, it } from 'vitest';
import { depthMarks } from './analytics';

describe('depthMarks', () => {
  it('reports each depth once, as the visitor passes it', () => {
    const sent = new Set<number>();
    expect(depthMarks(900, 4000, sent)).toEqual([]);
    expect(depthMarks(2100, 4000, sent)).toEqual([25, 50]);
    [25, 50].forEach(mark => sent.add(mark));
    expect(depthMarks(2100, 4000, sent)).toEqual([]);
    expect(depthMarks(4000, 4000, sent)).toEqual([75, 100]);
  });

  it('counts a page shorter than the screen as fully seen', () => {
    expect(depthMarks(844, 600, new Set())).toEqual([25, 50, 75, 100]);
  });
});
