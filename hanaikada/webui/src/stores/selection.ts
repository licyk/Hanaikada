import { computed, ref } from 'vue';

export interface ClickModifiers {
  shiftKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
}

/**
 * Selection over one ordered list of keys: click selects one, Ctrl/Cmd toggles, Shift selects the
 * range from the last clicked item. Each grid owns one; ``keep`` holds a selection across folders.
 */
export function useSelection() {
  const keys = ref(new Set<string>());
  const anchor = ref<string | null>(null);
  const keep = ref(false);

  function click(key: string, order: string[], mods: ClickModifiers = {}) {
    if (mods.shiftKey && anchor.value && order.includes(anchor.value)) {
      const a = order.indexOf(anchor.value);
      const b = order.indexOf(key);
      const [lo, hi] = a < b ? [a, b] : [b, a];
      const next = mods.ctrlKey || mods.metaKey ? new Set(keys.value) : new Set<string>();
      for (const k of order.slice(lo, hi + 1)) next.add(k);
      keys.value = next;
      return;
    }
    if (mods.ctrlKey || mods.metaKey || keep.value) {
      toggle(key);
    } else {
      keys.value = new Set([key]);
    }
    anchor.value = key;
  }

  function toggle(key: string, on?: boolean) {
    const next = new Set(keys.value);
    const add = on ?? !next.has(key);
    if (add) next.add(key);
    else next.delete(key);
    keys.value = next;
    anchor.value = key;
  }

  function selectAll(order: string[]) {
    keys.value = new Set(order);
  }

  function clear() {
    keys.value = new Set();
    anchor.value = null;
  }

  /** Drop keys no longer in the list, unless the selection is kept across lists. */
  function prune(order: string[]) {
    if (keep.value) return;
    const present = new Set(order);
    const next = new Set([...keys.value].filter((k) => present.has(k)));
    if (next.size !== keys.value.size) keys.value = next;
  }

  const count = computed(() => keys.value.size);
  const has = (key: string) => keys.value.has(key);
  return { keys, anchor, keep, count, click, toggle, selectAll, clear, prune, has };
}

export type Selection = ReturnType<typeof useSelection>;
