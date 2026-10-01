import { describe, expect, it } from 'vitest';
import en from '@/i18n/en';
import ja from '@/i18n/ja';
import zhCN from '@/i18n/zh-CN';
import { detectLocale } from '@/i18n';

/** Every English message has one in each other language, and the placeholders agree. */
function flatten(tree: unknown, prefix = ''): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(tree as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') out.set(path, value);
    else if (Array.isArray(value)) out.set(path, value.join('|'));
    else for (const [k, v] of flatten(value, path)) out.set(k, v);
  }
  return out;
}
const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('messages', () => {
  const english = flatten(en);
  const translations = { 'zh-CN': flatten(zhCN), ja: flatten(ja) };
  for (const [locale, messages] of Object.entries(translations)) {
    it(`has the same keys in ${locale}`, () => {
      expect([...messages.keys()].sort()).toEqual([...english.keys()].sort());
    });
    it(`uses the same placeholders in ${locale}`, () => {
      const mismatched = [...english.entries()].filter(([k, v]) => JSON.stringify(placeholders(v)) !== JSON.stringify(placeholders(messages.get(k) ?? '')));
      expect(mismatched.map(([k]) => k)).toEqual([]);
    });
  }
});

describe('detectLocale', () => {
  it('picks the translation for the system language', () => {
    expect(detectLocale('zh-CN')).toBe('zh-CN');
    expect(detectLocale('zh-Hant-TW')).toBe('zh-CN');
    expect(detectLocale('zh')).toBe('zh-CN');
    expect(detectLocale('ja')).toBe('ja');
    expect(detectLocale('ja-JP')).toBe('ja');
    expect(detectLocale('en-GB')).toBe('en');
  });
  it('falls back to English for an unknown or unsupported language', () => {
    expect(detectLocale('fr-FR')).toBe('en');
    expect(detectLocale('zhx')).toBe('en');
    expect(detectLocale('jbx')).toBe('en');
    expect(detectLocale('')).toBe('en');
    expect(detectLocale(undefined)).toBe('en');
  });
});
