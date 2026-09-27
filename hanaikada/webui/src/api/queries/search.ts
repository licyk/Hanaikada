import { useInfiniteQuery, useQuery } from '@tanstack/vue-query';
import { computed, type MaybeRefOrGetter, toValue } from 'vue';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';
import type { SearchQuery } from '@/api/types';

export type QueryInput = Partial<SearchQuery>;

/** Pages of search results, keyset-paged by the server's cursor. */
export function useSearch(query: MaybeRefOrGetter<QueryInput>, enabled: MaybeRefOrGetter<boolean> = true) {
  return useInfiniteQuery({
    queryKey: computed(() => [...keys.search, 'pages', toValue(query)] as const),
    enabled: computed(() => toValue(enabled)),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => unwrap(api.POST('/api/v1/search', { body: { ...toValue(query), cursor: pageParam } as SearchQuery })),
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: (prev) => prev,
  });
}

export function useFacets(query: MaybeRefOrGetter<QueryInput>, enabled: MaybeRefOrGetter<boolean> = true) {
  return useQuery({
    queryKey: computed(() => [...keys.facets, toValue(query)] as const),
    enabled: computed(() => toValue(enabled)),
    queryFn: () => unwrap(api.POST('/api/v1/search/facets', { body: { ...toValue(query), cursor: null } as SearchQuery })),
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  });
}

export function useStats(rootIds: MaybeRefOrGetter<string[] | null>) {
  return useQuery({
    queryKey: computed(() => [...keys.stats, toValue(rootIds)] as const),
    queryFn: () => unwrap(api.GET('/api/v1/search/stats', { params: { query: { root_id: toValue(rootIds) ?? undefined } } })),
  });
}
