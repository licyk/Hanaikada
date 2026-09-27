import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query';
import { computed, type MaybeRefOrGetter, toValue } from 'vue';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';
import type { ListSort, S } from '@/api/types';

export const useRoots = () => useQuery({ queryKey: keys.roots, queryFn: () => unwrap(api.GET('/api/v1/library/roots')) });

export const detectLayout = (path: string) => unwrap(api.GET('/api/v1/library/detect-layout', { params: { query: { path } } }));

export const locatePath = (path: string) => unwrap(api.GET('/api/v1/library/locate', { params: { query: { path } } }));

export interface ListingOptions {
  sort: ListSort;
  desc: boolean;
  seed?: number;
}

const PAGE = 500;

/** A folder's listing, a page at a time. Subfolders come with the first page. */
export function useEntries(rootId: MaybeRefOrGetter<string | null>, path: MaybeRefOrGetter<string>, options: MaybeRefOrGetter<ListingOptions>, enabled: MaybeRefOrGetter<boolean> = true) {
  return useInfiniteQuery({
    queryKey: computed(() => [...keys.entries(toValue(rootId) ?? '', toValue(path)), toValue(options)] as const),
    enabled: computed(() => !!toValue(rootId) && toValue(enabled)),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const o = toValue(options);
      return unwrap(
        api.GET('/api/v1/library/roots/{root_id}/entries', {
          params: { path: { root_id: toValue(rootId)! }, query: { path: toValue(path), sort: o.sort, desc: o.desc, seed: o.seed, cursor: pageParam ?? undefined, limit: PAGE } },
        }),
      );
    },
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: (prev) => prev,
  });
}

/** "All folders": the output folders of every root side by side, fetched only while shown. */
export function useCombinedEntries(enabled: MaybeRefOrGetter<boolean>) {
  return useQuery({
    queryKey: keys.combined,
    enabled: computed(() => toValue(enabled)),
    queryFn: () => unwrap(api.GET('/api/v1/library/combined/entries')),
    placeholderData: (prev) => prev,
  });
}

/** One folder and its subfolders, for the lazily opening folder tree. */
export function useTree(rootId: MaybeRefOrGetter<string | null>, path: MaybeRefOrGetter<string>, enabled: MaybeRefOrGetter<boolean> = true) {
  return useQuery({
    queryKey: computed(() => keys.tree(toValue(rootId) ?? '', toValue(path))),
    enabled: computed(() => !!toValue(rootId) && toValue(enabled)),
    queryFn: () => unwrap(api.GET('/api/v1/library/roots/{root_id}/tree', { params: { path: { root_id: toValue(rootId)! }, query: { path: toValue(path), depth: 1 } } })),
    staleTime: 30_000,
  });
}

export const useThumbnailCache = () => useQuery({ queryKey: keys.thumbnailCache, queryFn: () => unwrap(api.GET('/api/v1/library/thumbnails')) });

/** Mutations for roots and file operations. Each invalidates what it affects; socket events do the rest. */
export function useLibraryMutations() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['library'] });
    qc.invalidateQueries({ queryKey: keys.search });
  };
  const refreshRoots = () => {
    qc.invalidateQueries({ queryKey: keys.roots });
    qc.invalidateQueries({ queryKey: keys.indexRoots });
  };
  return {
    addRoot: useMutation({ mutationFn: (body: S['RootCreate']) => unwrap(api.POST('/api/v1/library/roots', { body })), onSuccess: refreshRoots }),
    updateRoot: useMutation({
      mutationFn: ({ id, body }: { id: string; body: S['RootUpdate'] }) => unwrap(api.PATCH('/api/v1/library/roots/{root_id}', { params: { path: { root_id: id } }, body })),
      onSuccess: () => {
        refreshRoots();
        refresh();
      },
    }),
    removeRoot: useMutation({
      mutationFn: (id: string) => unwrap(api.DELETE('/api/v1/library/roots/{root_id}', { params: { path: { root_id: id } } })),
      onSuccess: () => {
        refreshRoots();
        refresh();
      },
    }),
    rename: useMutation({ mutationFn: (body: S['RenameRequest']) => unwrap(api.POST('/api/v1/library/rename', { body })), onSuccess: refresh }),
    move: useMutation({ mutationFn: (body: S['TransferRequest']) => unwrap(api.POST('/api/v1/library/move', { body })), onSuccess: refresh }),
    copy: useMutation({ mutationFn: (body: S['TransferRequest']) => unwrap(api.POST('/api/v1/library/copy', { body })), onSuccess: refresh }),
    remove: useMutation({ mutationFn: (body: S['DeleteRequest']) => unwrap(api.POST('/api/v1/library/delete', { body })), onSuccess: refresh }),
    createFolder: useMutation({ mutationFn: (body: S['FolderCreate']) => unwrap(api.POST('/api/v1/library/folders', { body })), onSuccess: refresh }),
    open: useMutation({ mutationFn: (body: S['OpenRequest']) => unwrap(api.POST('/api/v1/library/open', { body })) }),
    clearThumbnails: useMutation({
      mutationFn: () => unwrap(api.POST('/api/v1/library/thumbnails/clear')),
      onSuccess: (data) => qc.setQueryData(keys.thumbnailCache, data),
    }),
  };
}
