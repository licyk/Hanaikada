import { onActivated, onBeforeUnmount, watch, type Ref } from 'vue';

/**
 * Keeps an element's scroll position while its page is kept alive but not shown. A page's DOM
 * leaves the document when another page is shown, and the browser forgets the offset; this puts it
 * back when the page is shown again. Memory only, like the page itself.
 */
export function useKeepScroll(target: Ref<HTMLElement | null | undefined>, onRestore?: () => void) {
  let top = 0;
  let left = 0;
  const record = () => {
    const el = target.value;
    if (el?.isConnected) ({ scrollTop: top, scrollLeft: left } = el);
  };
  watch(
    target,
    (el, old) => {
      old?.removeEventListener('scroll', record);
      el?.addEventListener('scroll', record, { passive: true });
    },
    { immediate: true },
  );
  onActivated(() => {
    const el = target.value;
    if (!el) return;
    el.scrollTop = top;
    el.scrollLeft = left;
    onRestore?.();
  });
  onBeforeUnmount(() => target.value?.removeEventListener('scroll', record));
}
