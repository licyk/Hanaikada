import createClient, { type Middleware } from 'openapi-fetch';
import { BASE_URL } from '@/api/baseUrl';
import type { paths } from '@/api/schema';
import { useAuthStore } from '@/stores/auth';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = useAuthStore().token;
    if (token) request.headers.set('Authorization', `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401) useAuthStore().needed = true;
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: BASE_URL });
api.use(auth);

type Result<T> = { data?: T; error?: unknown; response: Response };

function toError(error: unknown, response: Response): ApiError {
  if (error && typeof error === 'object') {
    const e = error as { code?: string; message?: string; detail?: unknown };
    if (typeof e.message === 'string') return new ApiError(response.status, e.code ?? 'error', e.message, (e.detail as Record<string, unknown>) ?? {});
    if (Array.isArray(e.detail)) {
      const first = e.detail[0] as { msg?: string; loc?: unknown[] } | undefined;
      return new ApiError(response.status, 'invalid_input', first?.msg ?? 'Invalid input', { errors: e.detail });
    }
  }
  return new ApiError(response.status, 'error', `${response.status} ${response.statusText}`);
}

/** Await an openapi-fetch call and return its data, or throw an ApiError with the server's message. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) throw toError(error, response);
  return data as T;
}

const rootBase = (rootId: string) => `${BASE_URL}/api/v1/library/roots/${encodeURIComponent(rootId)}`;

/**
 * URL of a file inside a root. ``version`` is the file's mtime token from its listing: it makes the
 * URL change when the file does, so the server lets the browser cache it for a year. The token
 * cookie authenticates <img> requests.
 */
export function fileUrl(rootId: string, path: string, version?: string | null, download = false): string {
  const q = new URLSearchParams({ path });
  if (version) q.set('t', version);
  if (download) q.set('download', 'true');
  return `${rootBase(rootId)}/file?${q}`;
}

/** URL of a cached thumbnail, the shorter side at least ``size`` pixels. */
export function thumbUrl(rootId: string, path: string, version?: string | null, size = 256): string {
  const q = new URLSearchParams({ path, size: String(size) });
  if (version) q.set('t', version);
  return `${rootBase(rootId)}/thumbnail?${q}`;
}

/** URL of one raw chunk as a download (``workflow.json``, ``parameters.txt``). */
export function chunkUrl(imageId: number, key: string, inline = false): string {
  return `${BASE_URL}/api/v1/images/${imageId}/raw/${encodeURIComponent(key)}${inline ? '?inline=true' : ''}`;
}

/** Save a blob under a name through a temporary link. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Download a zip of files and folders. The server streams it; the browser collects it. */
export async function downloadZip(items: { root_id: string; path: string }[], name: string): Promise<void> {
  const token = useAuthStore().token;
  const response = await fetch(`${BASE_URL}/api/v1/library/zip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ items, name }),
  });
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* not JSON */
    }
    throw toError(body, response);
  }
  saveBlob(await response.blob(), `${name}.zip`);
}

/** Start a browser download of a URL, keeping the page. */
export function downloadUrl(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * Upload one file with the raw request body, reporting progress. fetch() cannot report upload
 * progress, so this uses XMLHttpRequest.
 */
export function uploadFile(
  params: { rootId: string; dir: string; name: string; onConflict?: 'error' | 'rename' },
  file: Blob,
  onProgress: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<{ root_id: string; path: string }> {
  return new Promise((resolve, reject) => {
    const q = new URLSearchParams({ root_id: params.rootId, path: params.dir, name: params.name, on_conflict: params.onConflict ?? 'error' });
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', `${BASE_URL}/api/v1/library/upload?${q}`);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    const token = useAuthStore().token;
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : file.size);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as { root_id: string; path: string });
      else reject(toError(body, new Response(null, { status: xhr.status, statusText: xhr.statusText })));
    };
    xhr.onerror = () => reject(new ApiError(0, 'network', 'Network error'));
    xhr.onabort = () => reject(new ApiError(0, 'aborted', 'Upload cancelled'));
    signal?.addEventListener('abort', () => xhr.abort());
    xhr.send(file);
  });
}
