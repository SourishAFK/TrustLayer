import { describe, expect, it } from 'vitest';
import { audienceFrom, leadSource, readNdjson } from './api';

describe('audienceFrom', () => {
  it('reads the audience tag and falls back to general', () => {
    expect(audienceFrom('?for=documents')).toBe('documents');
    expect(audienceFrom('?for=support-bots&utm_source=x')).toBe('support-bots');
    expect(audienceFrom('?for=everyone')).toBe('general');
    expect(audienceFrom('')).toBe('general');
  });
});

describe('leadSource', () => {
  it('keeps campaign tags, the tagged page and an outside referrer only', () => {
    const url = new URL('https://trustlayer.example/check/?for=product-teams&utm_source=linkedin&gclid=1');
    expect(leadSource(url, 'https://news.example/post/1?secret=x')).toEqual({
      page: '/check/?for=product-teams&utm_source=linkedin&gclid=1',
      utm_source: 'linkedin',
      referrer: 'https://news.example/post/1',
    });
    expect(leadSource(url, 'https://trustlayer.example/')).not.toHaveProperty('referrer');
    expect(leadSource(url, 'not a url')).not.toHaveProperty('referrer');
  });

  it('clips every value to what the API accepts', () => {
    const url = new URL(`https://trustlayer.example/check/?utm_campaign=${'a'.repeat(500)}`);
    const source = leadSource(url, '');
    expect(source.utm_campaign).toHaveLength(300);
    expect(source.page.length).toBeLessThanOrEqual(300);
  });
});

describe('readNdjson', () => {
  const stream = (...chunks: string[]) => new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      chunks.forEach(chunk => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });

  it('parses lines split across chunks, skips blanks, and keeps a final unterminated line', async () => {
    const seen: unknown[] = [];
    for await (const item of readNdjson(stream('{"a":', '1}\n\n{"b"', ':2}\n{"c":3}'))) seen.push(item);
    expect(seen).toEqual([{ a: 1 }, { b: 2 }, { c: 3 }]);
  });
});
