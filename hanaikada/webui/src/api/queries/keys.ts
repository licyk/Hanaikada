/** Stands for every root in Browse's root selector ("All folders"); the server refuses it as a root id. */
export const COMBINED_VIEW_ID = '*';

/** Query keys, shared by the query modules and the socket handlers. */
export const keys = {
  meta: ['app', 'meta'] as const,
  version: ['app', 'version'] as const,
  settings: ['settings'] as const,
  clientState: (key: string) => ['client-state', key] as const,
  roots: ['library', 'roots'] as const,
  thumbnailCache: ['library', 'thumbnails'] as const,
  /** Every listing of a root, or of one folder of it. */
  entries: (rootId: string, path?: string) => (path === undefined ? (['library', 'entries', rootId] as const) : (['library', 'entries', rootId, path] as const)),
  /** "All folders": every root's output folders. Any root's change may touch it (a cover, a folder). */
  combined: ['library', 'entries', COMBINED_VIEW_ID] as const,
  tree: (rootId: string, path?: string) => (path === undefined ? (['library', 'tree', rootId] as const) : (['library', 'tree', rootId, path] as const)),
  images: ['images'] as const,
  image: (id: number) => ['images', 'id', id] as const,
  imageByPath: (rootId: string, path: string) => ['images', 'path', rootId, path] as const,
  raw: (id: number) => ['images', 'raw', id] as const,
  search: ['search'] as const,
  facets: ['search', 'facets'] as const,
  stats: ['search', 'stats'] as const,
  tags: ['tags'] as const,
  indexStatus: ['index', 'status'] as const,
  indexRoots: ['index', 'roots'] as const,
};
