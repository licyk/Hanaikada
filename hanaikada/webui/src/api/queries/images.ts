import { useQuery } from '@tanstack/vue-query';
import { computed, type MaybeRefOrGetter, toValue } from 'vue';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';

/** The detail of the image at a path, indexed on demand by the server when the index is behind. */
export function useImageByPath(rootId: MaybeRefOrGetter<string | null>, path: MaybeRefOrGetter<string | null>, version: MaybeRefOrGetter<string | null> = null) {
  return useQuery({
    queryKey: computed(() => [...keys.imageByPath(toValue(rootId) ?? '', toValue(path) ?? ''), toValue(version)] as const),
    enabled: computed(() => !!toValue(rootId) && !!toValue(path)),
    queryFn: () => unwrap(api.GET('/api/v1/images/by-path', { params: { query: { root_id: toValue(rootId)!, path: toValue(path)! } } })),
    staleTime: 60_000,
  });
}

export function useRaw(imageId: MaybeRefOrGetter<number | null>, enabled: MaybeRefOrGetter<boolean> = true) {
  return useQuery({
    queryKey: computed(() => keys.raw(toValue(imageId) ?? 0)),
    enabled: computed(() => !!toValue(imageId) && toValue(enabled)),
    queryFn: () => unwrap(api.GET('/api/v1/images/{image_id}/raw', { params: { path: { image_id: toValue(imageId)! } } })),
    staleTime: 60_000,
  });
}

/** Parse a dropped file without storing it: the PNG Info view. */
export async function parseFile(file: File) {
  return unwrap(
    api.POST('/api/v1/images/parse', {
      params: { query: { name: file.name } },
      body: file as never,
      bodySerializer: (body: unknown) => body as BodyInit,
      headers: { 'Content-Type': 'application/octet-stream' },
    }),
  );
}

export const fetchSimilar = (imageId: number, by: 'seed' | 'model' | 'prompt') =>
  unwrap(api.GET('/api/v1/images/{image_id}/similar', { params: { path: { image_id: imageId }, query: { by } } }));
