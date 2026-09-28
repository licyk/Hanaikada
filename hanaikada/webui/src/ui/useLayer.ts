import { onBeforeUnmount, watch } from 'vue';

/**
 * The layers open over the page — dialogs, sheets, the viewer, the compare view, menus — in the
 * order they opened. Only the topmost answers the keyboard: Escape closes it alone (not the viewer
 * under a delete dialog too), and a layer beneath leaves its shortcuts alone until it is on top
 * again. How they are drawn is the ``--app-z-*`` tokens' job.
 */
interface Layer {
  close: () => void;
}

const stack: Layer[] = [];

function onKey(event: KeyboardEvent) {
  // Something inside (a select's own menu) has already dealt with it.
  if (event.key !== 'Escape' || event.defaultPrevented || !stack.length) return;
  event.preventDefault();
  stack[stack.length - 1].close();
}

function remove(layer: Layer) {
  const i = stack.indexOf(layer);
  if (i < 0) return;
  stack.splice(i, 1);
  if (!stack.length) document.removeEventListener('keydown', onKey);
}

/** Register a layer shown while ``open()`` holds; Escape calls ``close`` when it is on top. */
export function useLayer(open: () => boolean, close: () => void) {
  const layer: Layer = { close };
  // Synchronous, so a layer closed by a key is off the stack before the next listener asks.
  watch(
    open,
    (value) => {
      remove(layer);
      if (!value) return;
      if (!stack.length) document.addEventListener('keydown', onKey);
      stack.push(layer);
    },
    { immediate: true, flush: 'sync' },
  );
  onBeforeUnmount(() => remove(layer));
  return { isTop: () => stack[stack.length - 1] === layer };
}

/** Whether any layer is open over the page. */
export const layerOpen = () => stack.length > 0;
