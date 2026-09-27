/**
 * Change indicators between neighbouring images: which generation values differ, and how two
 * prompts differ token by token. Computed on the client from the records the grid already has.
 */
import type { GenerationInfo } from '@/api/types';

export type FieldName = 'prompt' | 'negative_prompt' | 'seed' | 'steps' | 'cfg_scale' | 'sampler' | 'scheduler' | 'model' | 'size' | 'loras' | 'denoise';

function value(info: GenerationInfo, field: FieldName): string {
  switch (field) {
    case 'model':
      return info.model?.name ?? '';
    case 'size':
      return info.width && info.height ? `${info.width}x${info.height}` : '';
    case 'loras':
      return info.loras.map((l) => `${l.name}:${l.weight ?? ''}`).join(',');
    default: {
      const v = info[field];
      return v === null || v === undefined ? '' : String(v);
    }
  }
}

export const DIFF_FIELDS: FieldName[] = ['prompt', 'negative_prompt', 'seed', 'steps', 'cfg_scale', 'sampler', 'scheduler', 'model', 'size', 'loras', 'denoise'];

/** The fields whose values differ between two records. */
export function changedFields(a: GenerationInfo, b: GenerationInfo): FieldName[] {
  return DIFF_FIELDS.filter((f) => value(a, f) !== value(b, f));
}

/** Split a prompt into comma-separated tokens, keeping their text as written. */
export function promptTokens(prompt: string | null | undefined): string[] {
  if (!prompt) return [];
  return prompt
    .split(/,|\n/)
    .map((t) => t.trim())
    .filter(Boolean);
}

export interface TokenDiff {
  text: string;
  change: 'same' | 'added' | 'removed';
}

/**
 * The tokens of ``current`` marked as added or kept relative to ``previous``, then the tokens of
 * ``previous`` that are gone. Order is kept; comparison ignores case and surrounding space.
 */
export function diffPrompts(previous: string | null | undefined, current: string | null | undefined): TokenDiff[] {
  const before = promptTokens(previous);
  const after = promptTokens(current);
  const norm = (t: string) => t.toLowerCase();
  const beforeSet = new Set(before.map(norm));
  const afterSet = new Set(after.map(norm));
  return [
    ...after.map((text) => ({ text, change: beforeSet.has(norm(text)) ? ('same' as const) : ('added' as const) })),
    ...before.filter((t) => !afterSet.has(norm(t))).map((text) => ({ text, change: 'removed' as const })),
  ];
}

/** ``<lora:name:0.8>`` tags in a prompt, for highlighting. Returns the prompt split into plain and tag parts. */
export function splitExtraNetworks(prompt: string): { text: string; tag: boolean }[] {
  const out: { text: string; tag: boolean }[] = [];
  const re = /<(\w+):([^>]+)>/g;
  let last = 0;
  for (let m = re.exec(prompt); m; m = re.exec(prompt)) {
    if (m.index > last) out.push({ text: prompt.slice(last, m.index), tag: false });
    out.push({ text: m[0], tag: true });
    last = m.index + m[0].length;
  }
  if (last < prompt.length) out.push({ text: prompt.slice(last), tag: false });
  return out;
}

/** An A1111 infotext rebuilt from a record, for "copy infotext" on images from any platform. */
export function toInfotext(info: GenerationInfo): string {
  const lines: string[] = [];
  if (info.prompt) lines.push(info.prompt);
  if (info.negative_prompt) lines.push(`Negative prompt: ${info.negative_prompt}`);
  const params: [string, unknown][] = [
    ['Steps', info.steps],
    ['Sampler', info.sampler],
    ['Schedule type', info.scheduler],
    ['CFG scale', info.cfg_scale],
    ['Distilled CFG Scale', info.distilled_cfg],
    ['Seed', info.seed],
    ['Size', info.width && info.height ? `${info.width}x${info.height}` : null],
    ['Model hash', info.model?.hash_kind?.startsWith('sha256') ? info.model.hash : null],
    ['Model', info.model?.name],
    ['VAE', info.vae?.name],
    ['Denoising strength', info.denoise],
    ['Clip skip', info.clip_skip],
    ['Version', info.platform_version],
  ];
  const quote = (v: string) => (/[,:\n]/.test(v) ? JSON.stringify(v) : v);
  const parts = params.filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => `${k}: ${quote(String(v))}`);
  if (parts.length) lines.push(parts.join(', '));
  return lines.join('\n');
}
