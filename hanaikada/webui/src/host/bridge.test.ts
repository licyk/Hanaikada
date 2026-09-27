import { describe, expect, it, vi } from 'vitest';
import { createHostBridge, NS, parseHostInfo, PROTOCOL, type SendPayload, targetAccepts } from '@/host/bridge';

const ORIGIN = 'http://127.0.0.1:7860';
const payload: SendPayload = {
  item: { root_id: 'r1', path: 'out/a.png', name: 'a.png', kind: 'image', url: `${ORIGIN}/hanaikada/a.png`, version: '1', size: 10 },
  infotext: 'a cat\nSteps: 20',
  platform: 'sd-webui',
};

/** A bridge with a fake parent and hand-driven timers. */
function setup() {
  const posted: Record<string, unknown>[] = [];
  const parent = { postMessage: vi.fn((message: Record<string, unknown>, origin: string) => posted.push({ ...message, origin })) };
  const timers: { fn: () => void; ms: number; done: boolean }[] = [];
  const onHost = vi.fn();
  const bridge = createHostBridge({
    parent,
    origin: ORIGIN,
    onHost,
    helloAt: [0, 1000],
    timeoutMs: 5000,
    schedule: (fn, ms) => {
      const timer = { fn, ms, done: false };
      timers.push(timer);
      return timer;
    },
    cancel: (timer) => ((timer as { done: boolean }).done = true),
  });
  const run = (ms: number) => timers.filter((x) => x.ms === ms && !x.done).forEach((x) => ((x.done = true), x.fn()));
  const from = (data: unknown, source: unknown = parent, origin = ORIGIN) => bridge.handle({ data, source, origin });
  return { bridge, parent, posted, onHost, run, from };
}

describe('host bridge', () => {
  it('says hello to its parent on its own origin until a host answers', () => {
    const { posted, run, from } = setup();
    run(0);
    expect(posted).toEqual([{ ns: NS, v: PROTOCOL, type: 'hello', app: 'hanaikada', origin: ORIGIN }]);
    from({ ns: NS, v: PROTOCOL, type: 'host', host: { name: 'sd-webui', targets: [{ id: 'txt2img' }] } });
    run(1000);
    expect(posted).toHaveLength(1);
  });

  it('listens only to its parent, on its own origin, speaking the protocol', () => {
    const { onHost, from } = setup();
    const offer = { ns: NS, v: PROTOCOL, type: 'host', host: { name: 'x', targets: [{ id: 'txt2img' }] } };
    from(offer, {}, ORIGIN);
    from(offer, undefined, 'http://evil.example');
    from({ ...offer, v: 2 });
    from({ ...offer, ns: 'other' });
    expect(onHost).not.toHaveBeenCalled();
    from(offer);
    expect(onHost).toHaveBeenCalledWith({ name: 'x', label: undefined, targets: [{ id: 'txt2img', label: undefined, kinds: undefined, platforms: undefined, needs: undefined }] });
  });

  it('treats an empty offer as no host', () => {
    const { onHost, from } = setup();
    from({ ns: NS, v: PROTOCOL, type: 'host', host: { name: 'x', targets: [] } });
    expect(onHost).toHaveBeenCalledWith(null);
  });

  it('matches results to requests, and times out', async () => {
    const { bridge, posted, from, run } = setup();
    const sent = bridge.send('img2img', payload);
    const request = posted.at(-1)!;
    expect(request).toMatchObject({ type: 'send', target: 'img2img', payload });
    from({ ns: NS, v: PROTOCOL, type: 'result', id: request.id, ok: true });
    await expect(sent).resolves.toEqual({ ok: true, message: undefined });

    const slow = bridge.send('img2img', payload);
    run(5000);
    await expect(slow).resolves.toEqual({ ok: false, message: 'timeout' });
  });

  it('does nothing without a parent', async () => {
    const onHost = vi.fn();
    const bridge = createHostBridge({ parent: null, origin: ORIGIN, onHost });
    await expect(bridge.send('txt2img', payload)).resolves.toEqual({ ok: false, message: 'no host' });
    bridge.stop();
  });
});

describe('host offers', () => {
  it('keeps only well-formed targets and known values', () => {
    expect(parseHostInfo({ name: 'c', targets: [{ id: 'workflow', kinds: ['image', 'video', 'bogus'], needs: ['file', 'x'] }, { label: 'no id' }, 3] })).toEqual({
      name: 'c',
      label: undefined,
      targets: [{ id: 'workflow', label: undefined, kinds: ['image', 'video'], platforms: undefined, needs: ['file'] }],
    });
    expect(parseHostInfo({ targets: [] })).toBeNull();
  });

  it('filters by file kind (images by default) and platform', () => {
    expect(targetAccepts({ id: 'txt2img' }, 'image', null)).toBe(true);
    expect(targetAccepts({ id: 'txt2img' }, 'video', null)).toBe(false);
    expect(targetAccepts({ id: 'loadVideo', kinds: ['video'] }, 'video', null)).toBe(true);
    expect(targetAccepts({ id: 'workflow', platforms: ['comfyui'] }, 'image', 'comfyui')).toBe(true);
    expect(targetAccepts({ id: 'workflow', platforms: ['comfyui'] }, 'image', 'sd-webui')).toBe(false);
    expect(targetAccepts({ id: 'workflow', platforms: ['comfyui'] }, 'image', null)).toBe(false);
  });
});
