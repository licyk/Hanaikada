import { onScopeDispose, watch } from 'vue';

/**
 * The layers open over the page — dialogs, sheets, the viewer, the compare view, menus, Browse's
 * drawer — in the order they opened. They share one keyboard: each listening on the document for
 * itself let one Escape close several, a viewer beneath a dialog step on the dialog's arrows, and a
 * dialog's Tab trap pull focus out of whatever opened above it. So they register here, and only
 * the topmost receives keys. How they are drawn is the ``--app-z-*`` tokens' job.
 */
export type KeyHandler = (event: KeyboardEvent) => void;
interface Layer {
  onKey: KeyHandler;
}

const stack: Layer[] = [];

function dispatch(event: KeyboardEvent) {
  // A control inside the layer that handled the key itself (a select closing its own list) has claimed it.
  if (event.defaultPrevented) return;
  stack[stack.length - 1]?.onKey(event);
}

function remove(layer: Layer) {
  const i = stack.indexOf(layer);
  if (i < 0) return;
  stack.splice(i, 1);
  if (!stack.length) document.removeEventListener('keydown', dispatch);
}

/**
 * Register a layer while ``active()`` holds, topmost from the moment it becomes active. ``onKey``
 * sees every key pressed while the layer is on top; a key it acts on should be ``preventDefault``-ed,
 * so listeners outside the stack can tell. A page kept alive in the background passes an ``active``
 * that is false while hidden, so it never holds the keyboard.
 */
export function useLayer(active: () => boolean, onKey: KeyHandler) {
  const layer: Layer = { onKey };
  // Synchronous, so a layer closed by a key is off the stack before the next listener asks.
  watch(
    active,
    (value) => {
      remove(layer);
      if (!value) return;
      if (!stack.length) document.addEventListener('keydown', dispatch);
      stack.push(layer);
    },
    { immediate: true, flush: 'sync' },
  );
  onScopeDispose(() => remove(layer));
  return { isTop: () => stack[stack.length - 1] === layer };
}

/** A key handler for a layer whose only key is Escape, which calls ``close``. */
export const closeOnEscape =
  (close: () => void): KeyHandler =>
  (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    close();
  };

/** Whether any layer is open over the page. */
export const layerOpen = () => stack.length > 0;

const FOCUSABLE = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'video[controls]',
  'audio[controls]',
  '[tabindex]:not([tabindex="-1"])',
  'md-filled-button',
  'md-outlined-button',
  'md-text-button',
  'md-filled-tonal-button',
  'md-icon-button',
  'md-filled-tonal-icon-button',
].join(', ');

/** Keep Tab and Shift+Tab cycling inside ``container``; focus outside it is brought back in. */
export function trapFocus(event: KeyboardEvent, container: HTMLElement | null) {
  if (event.key !== 'Tab' || !container) return;
  const focusable = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute('disabled'));
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const inside = container.contains(document.activeElement);
  if (event.shiftKey && (document.activeElement === first || !inside)) {
    last.focus();
    event.preventDefault();
  } else if (!event.shiftKey && (document.activeElement === last || !inside)) {
    first.focus();
    event.preventDefault();
  }
}
