import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';
import { ref } from 'vue';
import type { ImageItem } from '@/api/types';
import { useSelection } from '@/stores/selection';
import { useViewerStore } from '@/stores/viewer';

const item = (n: number): ImageItem => ({ key: `r:${n}.png`, kind: 'image', rootId: 'r', path: `${n}.png`, name: `${n}.png`, version: '1', size: 1, mtime: '', indexed: true, image: null });

describe('viewer list navigation', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('walks the list it was opened from and fetches the next page at the end', async () => {
    const list = ref([item(1), item(2)]);
    let loads = 0;
    const viewer = useViewerStore();
    viewer.show({ items: () => list.value, hasMore: () => loads === 0, loadMore: async () => ((loads += 1), (list.value = [...list.value, item(3)])) }, 'r:1.png');
    expect(viewer.index).toBe(0);
    await viewer.next();
    expect(viewer.current?.name).toBe('2.png');
    await viewer.next();
    expect(loads).toBe(1);
    expect(viewer.current?.name).toBe('3.png');
    await viewer.next();
    expect(viewer.current?.name).toBe('3.png');
    viewer.previous();
    expect(viewer.previousItem?.name).toBe('1.png');
  });

  it('follows the current image when the list changes, and moves on after a delete', () => {
    const list = ref([item(1), item(2), item(3)]);
    const viewer = useViewerStore();
    viewer.show({ items: () => list.value }, 'r:2.png');
    list.value = [item(0), ...list.value];
    expect(viewer.index).toBe(2);
    const before = [...list.value];
    list.value = list.value.filter((i) => i.key !== 'r:2.png');
    viewer.removed('r:2.png', before);
    expect(viewer.current?.name).toBe('3.png');
    viewer.removed('r:3.png', [item(3)]);
    expect(viewer.open).toBe(false);
  });
});

describe('selection', () => {
  const order = ['a', 'b', 'c', 'd', 'e'];

  it('selects one, toggles with Ctrl, extends a range with Shift', () => {
    const s = useSelection();
    s.click('b', order);
    expect([...s.keys.value]).toEqual(['b']);
    s.click('d', order, { ctrlKey: true });
    expect([...s.keys.value].sort()).toEqual(['b', 'd']);
    s.click('a', order, { shiftKey: true });
    expect([...s.keys.value].sort()).toEqual(['a', 'b', 'c', 'd']);
    s.click('e', order);
    expect([...s.keys.value]).toEqual(['e']);
  });

  it('prunes vanished keys unless kept', () => {
    const s = useSelection();
    s.selectAll(order);
    s.prune(['a', 'b']);
    expect(s.count.value).toBe(2);
    s.keep.value = true;
    s.prune([]);
    expect(s.count.value).toBe(2);
    s.click('c', order);
    expect(s.count.value).toBe(3);
  });
});
