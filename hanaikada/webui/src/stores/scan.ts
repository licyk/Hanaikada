import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { RootScanState, ScanStatus, ServerEvents } from '@/api/types';

/**
 * The scanner's state, per root. REST gives a snapshot on connect; socket events keep it current.
 * High-frequency progress lives here rather than in the query cache.
 */
export const useScanStore = defineStore('scan', () => {
  const roots = ref<Record<string, RootScanState>>({});
  const queued = ref(0);
  const running = ref(false);
  const sheetOpen = ref(false);

  function setStatus(status: ScanStatus) {
    const next: Record<string, RootScanState> = {};
    for (const r of status.roots) next[r.root_id] = r;
    roots.value = next;
    queued.value = status.queued;
    running.value = status.running;
  }

  function patch(rootId: string, values: Partial<RootScanState>) {
    const current = roots.value[rootId] ?? ({ root_id: rootId, state: 'idle', full: false, folders_seen: 0, files_seen: 0, files_indexed: 0, files_failed: 0, current: null, started_at: null, finished_at: null, error: null } as RootScanState);
    roots.value = { ...roots.value, [rootId]: { ...current, ...values } };
  }

  const onStarted = (e: ServerEvents['scan_started']) => {
    running.value = true;
    patch(e.root_id, { state: 'scanning', full: e.full, folders_seen: 0, files_seen: 0, files_indexed: 0, files_failed: 0, current: null, error: null, started_at: new Date().toISOString(), finished_at: null });
  };
  const onProgress = (e: ServerEvents['scan_progress']) =>
    patch(e.root_id, { state: 'scanning', folders_seen: e.folders_seen, files_seen: e.files_seen, files_indexed: e.files_indexed, files_failed: e.files_failed, current: e.current ?? null });
  const onCompleted = (e: ServerEvents['scan_completed']) => {
    patch(e.root_id, { state: 'idle', folders_seen: e.folders_seen, files_seen: e.files_seen, files_indexed: e.files_indexed, files_failed: e.files_failed, current: null, finished_at: new Date().toISOString() });
    running.value = Object.values(roots.value).some((r) => r.state === 'scanning');
  };
  const onFailed = (e: ServerEvents['scan_failed']) => {
    patch(e.root_id, { state: 'failed', error: e.error, current: null, finished_at: new Date().toISOString() });
    running.value = Object.values(roots.value).some((r) => r.state === 'scanning');
  };

  const active = computed(() => Object.values(roots.value).filter((r) => r.state === 'scanning' || r.state === 'queued'));
  const indexedNow = computed(() => active.value.reduce((n, r) => n + r.files_indexed, 0));

  return { roots, queued, running, sheetOpen, active, indexedNow, setStatus, onStarted, onProgress, onCompleted, onFailed };
});
