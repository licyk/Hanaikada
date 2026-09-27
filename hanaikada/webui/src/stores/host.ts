import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { ImageItem } from '@/api/types';
import { createHostBridge, type HostBridge, type HostInfo, type HostTarget, type SendPayload, type SendResult, targetAccepts } from '@/host/bridge';

/**
 * The application framing Hanaikada, if any, and what it takes ("Send to txt2img", "Open workflow").
 * Nothing connects when Hanaikada runs in its own window; see ``host/bridge.ts`` for the protocol.
 */
export const useHostStore = defineStore('host', () => {
  const info = ref<HostInfo | null>(null);
  let bridge: HostBridge | null = null;

  function connect() {
    if (bridge || typeof window === 'undefined' || window.parent === window) return;
    bridge = createHostBridge({ parent: window.parent, origin: window.location.origin, onHost: (next) => (info.value = next) });
    window.addEventListener('message', (event) => bridge?.handle(event));
  }

  /** The targets that take this file; none without a host. */
  const targetsFor = (item: ImageItem): HostTarget[] => (info.value?.targets ?? []).filter((t) => targetAccepts(t, item.kind, item.image?.platform));

  const send = (target: HostTarget, payload: SendPayload): Promise<SendResult> => (bridge ? bridge.send(target.id, payload) : Promise.resolve({ ok: false, message: 'no host' }));

  return { info, connect, targetsFor, send };
});
