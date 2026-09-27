import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query';
import { computed, type MaybeRefOrGetter, toValue } from 'vue';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';
import type { S, TagType } from '@/api/types';

export function useTags(type: MaybeRefOrGetter<TagType | null> = null, q: MaybeRefOrGetter<string> = '', limit = 500) {
  return useQuery({
    queryKey: computed(() => [...keys.tags, toValue(type), toValue(q), limit] as const),
    queryFn: () => unwrap(api.GET('/api/v1/tags', { params: { query: { type: toValue(type) ?? undefined, q: toValue(q) || undefined, limit } } })),
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  });
}

/** The custom tags, which the grid's dots and the tag picker show. */
export const useCustomTags = () => useTags('custom', '', 1000);

export function useTagMutations() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.tags });
    qc.invalidateQueries({ queryKey: keys.images });
    qc.invalidateQueries({ queryKey: ['library', 'entries'] });
    qc.invalidateQueries({ queryKey: keys.search });
  };
  return {
    create: useMutation({ mutationFn: (body: S['TagCreate']) => unwrap(api.POST('/api/v1/tags', { body })), onSuccess: refresh }),
    update: useMutation({ mutationFn: ({ id, body }: { id: number; body: S['TagUpdate'] }) => unwrap(api.PATCH('/api/v1/tags/{tag_id}', { params: { path: { tag_id: id } }, body })), onSuccess: refresh }),
    remove: useMutation({ mutationFn: (id: number) => unwrap(api.DELETE('/api/v1/tags/{tag_id}', { params: { path: { tag_id: id } } })), onSuccess: refresh }),
    apply: useMutation({
      mutationFn: ({ id, body, add }: { id: number; body: S['TagImagesRequest']; add: boolean }) =>
        add
          ? unwrap(api.POST('/api/v1/tags/{tag_id}/images', { params: { path: { tag_id: id } }, body }))
          : unwrap(api.DELETE('/api/v1/tags/{tag_id}/images', { params: { path: { tag_id: id } }, body })),
      onSuccess: refresh,
    }),
  };
}
