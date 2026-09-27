/**
 * The host bridge: how Hanaikada, framed by another application (the SD WebUI or ComfyUI
 * extension), learns what that application can take and hands it an image.
 *
 * Protocol, version 1. Every message is ``{ ns: 'hanaikada', v: 1, type, ... }`` posted between
 * Hanaikada's frame and its parent window, on Hanaikada's own origin only:
 *
 * - Hanaikada → host  ``hello``  ``{ app: 'hanaikada' }``, sent at start-up and repeated a few times
 *   until a host answers.
 * - host → Hanaikada  ``host``   ``{ host: { name, label?, targets: [{ id, label?, kinds?, platforms?, needs? }] } }``,
 *   in answer to ``hello`` or at any time to change the offer; ``targets: []`` withdraws it.
 * - Hanaikada → host  ``send``   ``{ id, target, payload: SendPayload }``.
 * - host → Hanaikada  ``result`` ``{ id, ok, message? }``.
 *
 * With no parent, or a parent that never answers, nothing changes in the interface.
 */

export const NS = 'hanaikada';
export const PROTOCOL = 1;

export type ItemKind = 'image' | 'video' | 'audio' | 'file';

export interface HostTarget {
  /** ``txt2img``, ``img2img``, ``inpaint``, ``extras``, ``workflow``, ``loadImage``, or a host's own. */
  id: string;
  /** Shown instead of Hanaikada's own label for a known id. */
  label?: string;
  /** Which files the target takes; images only when absent. */
  kinds?: ItemKind[];
  /** Only images made by these platforms (``sd-webui``, ``comfyui``, …); any when absent. */
  platforms?: string[];
  /** What the host needs in the payload: the parameters as infotext, the file (always sent as a URL). */
  needs?: ('infotext' | 'file')[];
}

export interface HostInfo {
  name: string;
  label?: string;
  targets: HostTarget[];
}

export interface SendPayload {
  item: { root_id: string; path: string; name: string; kind: ItemKind; url: string; version: string; size: number };
  /** An A1111 infotext: the image's own when it has one, else rebuilt from its metadata; null when it has none. */
  infotext: string | null;
  platform: string | null;
}

export interface SendResult {
  ok: boolean;
  message?: string;
}

interface MessageLike {
  data: unknown;
  origin: string;
  source: unknown;
}

interface WindowLike {
  postMessage(message: unknown, targetOrigin: string): void;
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;
const KINDS: ItemKind[] = ['image', 'video', 'audio', 'file'];
const strings = (v: unknown): string[] | undefined => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : undefined);

/** A host's offer, keeping only well-formed targets; ``null`` when it is not one. */
export function parseHostInfo(value: unknown): HostInfo | null {
  if (!isObject(value) || typeof value.name !== 'string' || !Array.isArray(value.targets)) return null;
  const targets: HostTarget[] = [];
  for (const t of value.targets) {
    if (!isObject(t) || typeof t.id !== 'string' || !t.id) continue;
    targets.push({
      id: t.id,
      label: typeof t.label === 'string' ? t.label : undefined,
      kinds: strings(t.kinds)?.filter((k): k is ItemKind => (KINDS as string[]).includes(k)),
      platforms: strings(t.platforms),
      needs: strings(t.needs)?.filter((n): n is 'infotext' | 'file' => n === 'infotext' || n === 'file'),
    });
  }
  return { name: value.name, label: typeof value.label === 'string' ? value.label : undefined, targets };
}

/** Whether a target takes this file. */
export function targetAccepts(target: HostTarget, kind: ItemKind, platform: string | null | undefined): boolean {
  if (!(target.kinds?.length ? target.kinds : ['image']).includes(kind)) return false;
  return !target.platforms?.length || (!!platform && target.platforms.includes(platform));
}

export interface HostBridge {
  /** Handle one ``message`` event; exposed so tests need no real frames. */
  handle(event: MessageLike): void;
  send(target: string, payload: SendPayload): Promise<SendResult>;
  stop(): void;
}

export interface BridgeOptions {
  /** The parent window, or null when not framed. */
  parent: WindowLike | null;
  /** Hanaikada's own origin: the only one messages are sent to and accepted from. */
  origin: string;
  onHost(info: HostInfo | null): void;
  timeoutMs?: number;
  /** When to repeat ``hello`` while no host has answered (ms after start). */
  helloAt?: number[];
  schedule?: (fn: () => void, ms: number) => unknown;
  cancel?: (handle: unknown) => void;
}

export function createHostBridge(options: BridgeOptions): HostBridge {
  const { parent, origin } = options;
  const schedule = options.schedule ?? ((fn, ms) => setTimeout(fn, ms));
  const cancel = options.cancel ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>));
  const pending = new Map<string, { resolve: (r: SendResult) => void; timer: unknown }>();
  const timers: unknown[] = [];
  let answered = false;
  let counter = 0;

  const post = (message: Record<string, unknown>) => parent?.postMessage({ ns: NS, v: PROTOCOL, ...message }, origin);
  const hello = () => {
    if (!answered) post({ type: 'hello', app: 'hanaikada' });
  };
  if (parent) for (const ms of options.helloAt ?? [0, 1000, 3000]) timers.push(schedule(hello, ms));

  function handle(event: MessageLike) {
    // Only the frame's own parent, on our own origin, speaks for the host.
    if (!parent || event.source !== parent || event.origin !== origin) return;
    const data = event.data;
    if (!isObject(data) || data.ns !== NS || data.v !== PROTOCOL) return;
    if (data.type === 'host') {
      const info = parseHostInfo(data.host);
      if (!info) return;
      answered = true;
      options.onHost(info.targets.length ? info : null);
    } else if (data.type === 'result' && typeof data.id === 'string') {
      const request = pending.get(data.id);
      if (!request) return;
      pending.delete(data.id);
      cancel(request.timer);
      request.resolve({ ok: data.ok === true, message: typeof data.message === 'string' ? data.message : undefined });
    }
  }

  function send(target: string, payload: SendPayload): Promise<SendResult> {
    if (!parent) return Promise.resolve({ ok: false, message: 'no host' });
    const id = `${Date.now().toString(36)}-${++counter}`;
    return new Promise((resolve) => {
      const timer = schedule(() => {
        pending.delete(id);
        resolve({ ok: false, message: 'timeout' });
      }, options.timeoutMs ?? 20_000);
      pending.set(id, { resolve, timer });
      post({ type: 'send', id, target, payload });
    });
  }

  function stop() {
    timers.forEach(cancel);
    for (const { resolve, timer } of pending.values()) {
      cancel(timer);
      resolve({ ok: false, message: 'stopped' });
    }
    pending.clear();
  }

  return { handle, send, stop };
}
