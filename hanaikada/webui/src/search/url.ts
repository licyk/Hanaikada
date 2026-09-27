/**
 * A search serialised into the URL, so it can be reloaded, bookmarked and shared. Only the fields
 * that differ from the defaults are written; the result is URL-safe base64 of compact JSON.
 */
import type { SearchQuery } from '@/api/types';

export type QueryState = Partial<Omit<SearchQuery, 'cursor'>>;

const DEFAULTS: QueryState = { sort: 'mtime', descending: true, include_missing: false, limit: 200 };

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
}

/** Drop empty and default fields, so equal searches serialise equally. */
export function compactQuery(query: QueryState): QueryState {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(query)) {
    if (key === 'cursor' || isEmpty(value)) continue;
    if (Array.isArray(value) && value.length === 2 && value.every(isEmpty)) continue;
    if (DEFAULTS[key as keyof QueryState] === value) continue;
    out[key] = value;
  }
  return out as QueryState;
}

function toBase64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(text: string): string {
  const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
  const binary = atob(padded);
  return new TextDecoder().decode(Uint8Array.from(binary, (c) => c.charCodeAt(0)));
}

export function encodeQuery(query: QueryState): string {
  const compact = compactQuery(query);
  return Object.keys(compact).length ? toBase64Url(JSON.stringify(compact)) : '';
}

export function decodeQuery(encoded: string | null | undefined): QueryState {
  if (!encoded) return {};
  try {
    const value = JSON.parse(fromBase64Url(encoded));
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as QueryState) : {};
  } catch {
    return {};
  }
}

/** Equal when their compact forms are equal. */
export function sameQuery(a: QueryState, b: QueryState): boolean {
  return encodeQuery(a) === encodeQuery(b);
}
