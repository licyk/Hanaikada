import { describe, expect, it } from 'vitest';
import type { GenerationInfo } from '@/api/types';
import { changedFields, diffPrompts, promptTokens, splitExtraNetworks, toInfotext } from '@/metadata/infotext';

const base: GenerationInfo = {
  platform: 'sd-webui',
  platform_version: 'v1.10.1',
  mode: 'txt2img',
  family: null,
  prompt: '1girl, solo, <lora:ink:0.8>, cherry blossoms',
  negative_prompt: 'lowres',
  prompts: [],
  seed: 42,
  steps: 20,
  cfg_scale: 7,
  distilled_cfg: null,
  cfg_rescale: null,
  sampler: 'Euler a',
  scheduler: 'Karras',
  sampler_norm: 'euler_ancestral',
  width: 512,
  height: 768,
  denoise: null,
  clip_skip: 2,
  model: { name: 'anime', path: null, hash: '0123456789', hash_kind: 'sha256-10' },
  vae: null,
  loras: [{ name: 'ink', weight: 0.8, weight_clip: null, hash: null }],
  passes: [],
  controls: [],
  extras: {},
  sources: ['parameters'],
  warnings: [],
};

describe('change indicators', () => {
  it('lists the fields that differ', () => {
    expect(changedFields(base, { ...base })).toEqual([]);
    expect(changedFields(base, { ...base, seed: 43, width: 640 })).toEqual(['seed', 'size']);
    expect(changedFields(base, { ...base, loras: [] })).toEqual(['loras']);
  });

  it('diffs prompts token by token, ignoring case', () => {
    const diff = diffPrompts('1girl, solo, Red Hair', '1girl, red hair, smile');
    expect(diff).toEqual([
      { text: '1girl', change: 'same' },
      { text: 'red hair', change: 'same' },
      { text: 'smile', change: 'added' },
      { text: 'solo', change: 'removed' },
    ]);
    expect(diffPrompts(null, 'a')).toEqual([{ text: 'a', change: 'added' }]);
    expect(promptTokens('a,\nb, , c')).toEqual(['a', 'b', 'c']);
  });

  it('marks extra-network tags in a prompt', () => {
    expect(splitExtraNetworks('x <lora:ink:0.8> y')).toEqual([
      { text: 'x ', tag: false },
      { text: '<lora:ink:0.8>', tag: true },
      { text: ' y', tag: false },
    ]);
  });

  it('rebuilds an infotext for any platform', () => {
    const text = toInfotext(base);
    expect(text.split('\n')[0]).toBe(base.prompt);
    expect(text).toContain('Negative prompt: lowres');
    expect(text).toContain('Steps: 20, Sampler: Euler a, Schedule type: Karras, CFG scale: 7, Seed: 42, Size: 512x768, Model hash: 0123456789, Model: anime');
  });
});
