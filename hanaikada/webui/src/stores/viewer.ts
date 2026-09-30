import { defineStore } from 'pinia';
import { computed, ref, shallowRef } from 'vue';
import type { ImageItem } from '@/api/types';

/** Where the viewer's list comes from: the grid that opened it, which may page further. */
export interface ViewerSource {
  items: () => ImageItem[];
  hasMore?: () => boolean;
  loadMore?: () => Promise<unknown>;
}

/**
 * The full-screen viewer walks the list it was opened from. The current image is tracked by key,
 * so it survives the list changing under it (a new page, a deletion, a live listing update).
 */
export const useViewerStore = defineStore('viewer', () => {
  const open = ref(false);
  const source = shallowRef<ViewerSource | null>(null);
  const key = ref<string | null>(null);
  const loading = ref(false);

  const items = computed(() => source.value?.items() ?? []);
  const index = computed(() => items.value.findIndex((i) => i.key === key.value));
  const current = computed<ImageItem | null>(() => (index.value >= 0 ? items.value[index.value] : null));
  const previousItem = computed(() => (index.value > 0 ? items.value[index.value - 1] : null));

  function show(from: ViewerSource, startKey: string) {
    source.value = from;
    key.value = startKey;
    open.value = true;
  }

  function close() {
    open.value = false;
  }

  /** Fetch the source's next page, once at a time; false when there was nothing to fetch. */
  async function loadMore(): Promise<boolean> {
    const src = source.value;
    if (!src?.hasMore?.() || !src.loadMore || loading.value) return false;
    loading.value = true;
    try {
      await src.loadMore();
      return true;
    } finally {
      loading.value = false;
    }
  }

  async function next() {
    const list = items.value;
    if (index.value < 0) return;
    if (index.value < list.length - 1) {
      key.value = list[index.value + 1].key;
      return;
    }
    const before = list.length;
    if (!(await loadMore())) return;
    const after = items.value;
    if (after.length > before) key.value = after[before].key;
  }

  function previous() {
    if (index.value > 0) key.value = items.value[index.value - 1].key;
  }

  function goTo(k: string) {
    key.value = k;
  }

  /** After the current image is deleted: move to its neighbour, or close when the list is empty. */
  function removed(k: string, before: ImageItem[]) {
    if (k !== key.value) return;
    const at = before.findIndex((i) => i.key === k);
    const rest = before.filter((i) => i.key !== k);
    if (!rest.length) {
      close();
      return;
    }
    key.value = rest[Math.min(at, rest.length - 1)].key;
  }

  return { open, source, key, loading, items, index, current, previousItem, show, close, loadMore, next, previous, goTo, removed };
});
