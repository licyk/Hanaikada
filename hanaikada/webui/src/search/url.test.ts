import { describe, expect, it } from 'vitest';
import { compactQuery, decodeQuery, encodeQuery, sameQuery } from '@/search/url';

describe('search ↔ URL', () => {
  it('round-trips a query, text in any script included', () => {
    const query = { text: '桜 blossoms, (masterpiece:1.2)', text_in: ['prompt' as const], models: ['anime'], steps: [20, null] as [number, null], all_tags: [3, 4], sort: 'random' as const, random_seed: 7 };
    expect(decodeQuery(encodeQuery(query))).toEqual(query);
  });

  it('drops empty and default fields', () => {
    expect(compactQuery({ text: '', models: [], steps: [null, null], sort: 'mtime', descending: true, include_missing: false })).toEqual({});
    expect(encodeQuery({})).toBe('');
    expect(sameQuery({ text: 'a', models: [] }, { text: 'a' })).toBe(true);
  });

  it('ignores a malformed value', () => {
    expect(decodeQuery('not base64!')).toEqual({});
    expect(decodeQuery(null)).toEqual({});
  });

  it('never carries a cursor', () => {
    expect(decodeQuery(encodeQuery({ text: 'x', cursor: 'abc' } as never))).toEqual({ text: 'x' });
  });
});
