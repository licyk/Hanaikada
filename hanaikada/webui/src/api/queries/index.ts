import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';
import type { S } from '@/api/types';
import { useScanStore } from '@/stores/scan';

export const fetchIndexStatus = () => unwrap(api.GET('/api/v1/index/status'));

export const useIndexRoots = () => useQuery({ queryKey: keys.indexRoots, queryFn: () => unwrap(api.GET('/api/v1/index/roots')) });

export function useIndexMutations() {
  const qc = useQueryClient();
  const scan = useScanStore();
  return {
    scan: useMutation({
      mutationFn: (body: S['ScanRequest']) => unwrap(api.POST('/api/v1/index/scan', { body })),
      onSuccess: (status) => {
        scan.setStatus(status);
        qc.invalidateQueries({ queryKey: keys.indexRoots });
      },
    }),
    cancel: useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/index/cancel')), onSuccess: (status) => scan.setStatus(status) }),
  };
}
