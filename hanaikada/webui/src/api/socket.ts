import type { QueryClient, QueryKey } from '@tanstack/vue-query';
import { io, type Socket } from 'socket.io-client';
import { BASE_PATH, BASE_URL } from '@/api/baseUrl';
import { fetchIndexStatus } from '@/api/queries/index';
import { keys } from '@/api/queries/keys';
import type { ServerEvents } from '@/api/types';
import { parentPath } from '@/format';
import { useAuthStore } from '@/stores/auth';
import { useScanStore } from '@/stores/scan';
import { useUploadsStore } from '@/stores/uploads';

type Listeners = { [K in keyof ServerEvents]: (payload: ServerEvents[K]) => void };

let socket: Socket<Listeners> | null = null;

/**
 * Invalidate a query key at most once per interval. A scan sends an ``index_changed`` per batch of
 * files; refetching the visible folder for each would thrash, so changes are gathered first.
 */
export function createInvalidator(qc: QueryClient, delay = 400) {
  const pending = new Map<string, QueryKey>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const flush = () => {
    timer = undefined;
    for (const key of pending.values()) qc.invalidateQueries({ queryKey: key });
    pending.clear();
  };
  return (key: QueryKey) => {
    pending.set(JSON.stringify(key), key);
    if (!timer) timer = setTimeout(flush, delay);
  };
}

/**
 * Connect once. REST stays the source of truth: events invalidate the queries they affect, and a
 * reconnect refetches the scan status, the listings and the searches.
 */
export function connectSocket(qc: QueryClient): Socket<Listeners> {
  if (socket) return socket;
  const scan = useScanStore();
  const uploads = useUploadsStore();
  const invalidate = createInvalidator(qc);
  socket = io(new URL(BASE_URL).origin, {
    path: `${BASE_PATH}/ws/socket.io`,
    auth: (cb) => cb({ token: useAuthStore().token }),
    transports: ['websocket', 'polling'],
    // The server restarting is routine in development; back off instead of hammering it.
    reconnectionDelay: 1000,
    reconnectionDelayMax: 10_000,
  });

  const refreshStatus = () => fetchIndexStatus().then(scan.setStatus).catch(() => undefined);

  socket.on('connect', refreshStatus);
  socket.on('scan_started', scan.onStarted);
  socket.on('scan_progress', scan.onProgress);
  socket.on('scan_failed', scan.onFailed);
  socket.on('scan_completed', (e) => {
    scan.onCompleted(e);
    for (const key of [keys.search, keys.tags, keys.indexRoots, keys.combined, ['library', 'entries', e.root_id]]) invalidate(key);
  });
  socket.on('index_changed', (e) => {
    invalidate(keys.entries(e.root_id, e.rel_dir));
    // The folder's cover is part of its parent's listing.
    if (e.rel_dir) invalidate(keys.entries(e.root_id, parentPath(e.rel_dir)));
    invalidate(keys.combined);
    invalidate(keys.search);
    for (const path of [...(e.updated ?? []), ...(e.removed ?? [])]) invalidate(keys.imageByPath(e.root_id, path));
  });
  socket.on('library_changed', (e) => {
    invalidate(keys.entries(e.root_id, e.rel_path));
    invalidate(keys.tree(e.root_id, e.rel_path));
    invalidate(keys.combined);
  });
  socket.on('tags_changed', () => {
    invalidate(keys.tags);
    invalidate(keys.images);
  });
  socket.on('import_progress', (p) => uploads.onServerProgress(p.root_id, p.rel_path, p.bytes_done, p.done));
  socket.io.on('reconnect', () => {
    refreshStatus();
    qc.invalidateQueries({ queryKey: ['library'] });
    qc.invalidateQueries({ queryKey: keys.search });
  });
  return socket;
}

export function disconnectSocket() {
  socket?.disconnect();
  socket = null;
}
