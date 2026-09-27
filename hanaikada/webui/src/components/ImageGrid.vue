<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { ImageItem, PathRef } from '@/api/types';
import FolderCell from '@/components/FolderCell.vue';
import { DRAG_TYPE, type GridEntry, type GridFolder, isWholeRoot, moveFocus } from '@/components/gridKeyboard';
import ImageCell from '@/components/ImageCell.vue';
import { useI18n } from '@/i18n';
import type { Selection } from '@/stores/selection';
import { useWindowClass } from '@/theme/breakpoints';
import { ProgressCircle, VirtualGrid } from '@/ui';

/**
 * The grid every screen uses: folders first, then images. Click selects (Shift for a range,
 * Ctrl/Cmd to toggle), double-click or Enter opens, Space previews, Backspace goes up, Ctrl+A
 * selects all, Delete deletes. Cells drag onto folder cells to move or copy.
 */
const props = withDefaults(
  defineProps<{
    items: ImageItem[];
    /** Folders of ``rootId``, or folders that each carry their own ``root_id`` (All folders). */
    folders?: GridFolder[];
    rootId?: string | null;
    selection: Selection;
    cellSize: number;
    showNames: boolean;
    tagColors: Map<number, string | null>;
    favoriteId?: number | null;
    hasMore?: boolean;
    loadingMore?: boolean;
    label?: string;
  }>(),
  { folders: () => [], rootId: null, favoriteId: null },
);
const emit = defineEmits<{
  open: [ImageItem];
  preview: [ImageItem];
  openFolder: [path: string, rootId: string];
  nearEnd: [];
  context: [{ entry: GridEntry; x: number; y: number }];
  up: [];
  delete: [];
  transfer: [{ refs: PathRef[]; rootId: string; dir: string; copy: boolean }];
}>();
const { t } = useI18n();
const windowClass = useWindowClass();
// Two columns at least on a phone, whatever size the desktop was set to.
const minCell = computed(() => (windowClass.value === 'compact' ? Math.min(props.cellSize, 150) : props.cellSize));

const entries = computed<GridEntry[]>(() => [
  ...props.folders.map((folder) => {
    const rootId = folder.root_id ?? props.rootId ?? '';
    return { kind: 'folder' as const, key: `d:${rootId}:${folder.path}`, rootId, folder };
  }),
  ...props.items.map((item) => ({ kind: 'image' as const, key: item.key, item })),
]);
const order = computed(() => entries.value.map((e) => e.key));
/** What the virtual grid exposes; it is generic, so its instance type cannot be named directly. */
interface GridHandle {
  scrollToIndex: (index: number, align?: 'nearest' | 'start') => void;
  scrollToTop: () => void;
  columns: number;
}
const grid = ref<GridHandle | null>(null);
const focusIndex = ref(-1);
const dropKey = ref<string | null>(null);

watch(order, (keys) => {
  props.selection.prune(keys);
  if (focusIndex.value >= keys.length) focusIndex.value = keys.length - 1;
});

function refOf(entry: GridEntry): PathRef {
  return entry.kind === 'folder' ? { root_id: entry.rootId, path: entry.folder.path } : { root_id: entry.item.rootId, path: entry.item.path };
}

function activate(entry: GridEntry) {
  if (entry.kind === 'folder') emit('openFolder', entry.folder.path, entry.rootId);
  else emit('open', entry.item);
}

function onClick(entry: GridEntry, index: number, event: MouseEvent) {
  focusIndex.value = index;
  const touch = (event as PointerEvent).pointerType === 'touch';
  if (touch && !props.selection.count.value) {
    activate(entry);
    return;
  }
  props.selection.click(entry.key, order.value, touch ? { ctrlKey: true } : event);
}

function onKey(event: KeyboardEvent) {
  const total = entries.value.length;
  const columns = grid.value?.columns ?? 1;
  const next = moveFocus(focusIndex.value, event.key, columns, total);
  if (next !== null) {
    event.preventDefault();
    focusIndex.value = next;
    grid.value?.scrollToIndex(next);
    const entry = entries.value[next];
    if (event.shiftKey) props.selection.click(entry.key, order.value, { shiftKey: true });
    return;
  }
  const entry = entries.value[focusIndex.value];
  if (event.key === 'Enter' && entry) {
    event.preventDefault();
    activate(entry);
  } else if (event.key === ' ' && entry) {
    event.preventDefault();
    if (entry.kind === 'image') emit('preview', entry.item);
    else props.selection.toggle(entry.key);
  } else if (event.key === 'Backspace') {
    event.preventDefault();
    emit('up');
  } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
    event.preventDefault();
    props.selection.selectAll(order.value);
  } else if (event.key === 'Escape' && props.selection.count.value) {
    props.selection.clear();
  } else if (event.key === 'Delete' && (props.selection.count.value || entry)) {
    if (!props.selection.count.value && entry) props.selection.click(entry.key, order.value);
    emit('delete');
  }
}

// -- context menu and long press ---------------------------------------------------------------

let pressTimer: ReturnType<typeof setTimeout> | undefined;
function onPointerDown(entry: GridEntry, index: number, event: PointerEvent) {
  if (event.pointerType !== 'touch') return;
  clearTimeout(pressTimer);
  pressTimer = setTimeout(() => openContext(entry, index, event.clientX, event.clientY), 550);
}
const cancelPress = () => clearTimeout(pressTimer);

function openContext(entry: GridEntry, index: number, x: number, y: number) {
  focusIndex.value = index;
  if (!props.selection.has(entry.key)) props.selection.click(entry.key, order.value);
  emit('context', { entry, x, y });
}

// -- drag and drop ------------------------------------------------------------------------------

function onDragStart(entry: GridEntry, event: DragEvent) {
  if (!event.dataTransfer) return;
  const chosen = props.selection.has(entry.key) ? entries.value.filter((e) => props.selection.has(e.key)) : [entry];
  const refs = chosen.filter((e) => !isWholeRoot(e)).map(refOf);
  if (!refs.length) {
    event.preventDefault();
    return;
  }
  event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(refs));
  event.dataTransfer.setData('text/plain', refs.map((r) => `${r.root_id}:${r.path}`).join('\n'));
  event.dataTransfer.effectAllowed = 'copyMove';
}

const carriesRefs = (event: DragEvent) => !!event.dataTransfer && Array.from(event.dataTransfer.types).includes(DRAG_TYPE);

function onDragOver(entry: GridEntry, event: DragEvent) {
  if (entry.kind !== 'folder' || !carriesRefs(event)) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = event.ctrlKey || event.altKey ? 'copy' : 'move';
  dropKey.value = entry.key;
}

function onDrop(entry: GridEntry, event: DragEvent) {
  dropKey.value = null;
  if (entry.kind !== 'folder' || !carriesRefs(event) || !entry.rootId) return;
  event.preventDefault();
  event.stopPropagation();
  const refs = JSON.parse(event.dataTransfer!.getData(DRAG_TYPE)) as PathRef[];
  const target = entry.folder.path;
  const moving = refs.filter((r) => !(r.root_id === entry.rootId && (r.path === target || target.startsWith(`${r.path}/`))));
  if (moving.length) emit('transfer', { refs: moving, rootId: entry.rootId, dir: target, copy: event.ctrlKey || event.altKey });
}

defineExpose({ scrollToTop: () => grid.value?.scrollToTop(), focusKey: (key: string) => {
  const i = order.value.indexOf(key);
  if (i >= 0) {
    focusIndex.value = i;
    grid.value?.scrollToIndex(i);
  }
} });
</script>

<template>
  <div class="image-grid" tabindex="0" :aria-label="label" @keydown="onKey">
    <VirtualGrid
      ref="grid"
      :items="entries"
      :item-key="(e: GridEntry) => e.key"
      :min-cell-width="minCell"
      :caption-height="showNames ? 24 : 0"
      :gap="8"
      :label="label"
      @near-end="hasMore && !loadingMore && emit('nearEnd')"
    >
      <template #default="{ item: entry, index, width }">
        <div
          class="slot"
          draggable="true"
          :aria-selected="selection.has(entry.key)"
          @click="onClick(entry, index, $event)"
          @dblclick="activate(entry)"
          @contextmenu.prevent="openContext(entry, index, $event.clientX, $event.clientY)"
          @pointerdown="onPointerDown(entry, index, $event)"
          @pointerup="cancelPress"
          @pointerleave="cancelPress"
          @pointermove="cancelPress"
          @dragstart="onDragStart(entry, $event)"
          @dragover="onDragOver(entry, $event)"
          @dragleave="dropKey = null"
          @drop="onDrop(entry, $event)"
        >
          <FolderCell
            v-if="entry.kind === 'folder'"
            :folder="entry.folder"
            :root-id="entry.rootId"
            :size="width"
            :show-name="showNames"
            :selected="selection.has(entry.key)"
            :focused="index === focusIndex"
            :dropping="dropKey === entry.key"
          />
          <ImageCell
            v-else
            :item="entry.item"
            :size="width"
            :show-name="showNames"
            :selected="selection.has(entry.key)"
            :focused="index === focusIndex"
            :tag-colors="tagColors"
            :favorite-id="favoriteId"
            :blurred="entry.item.image?.blur"
            @toggle-select="selection.toggle(entry.key)"
          />
        </div>
      </template>
      <template #after>
        <div v-if="loadingMore" class="more"><ProgressCircle :size="28" :label="t('common.loading')" /></div>
      </template>
    </VirtualGrid>
  </div>
</template>

<style scoped>
.image-grid { position: relative; height: 100%; min-height: 0; outline: none; padding: 0 var(--app-space-2) 0 var(--app-space-4); }
.image-grid:focus-visible { outline: 2px solid var(--md-sys-color-secondary); outline-offset: -2px; border-radius: var(--md-sys-shape-corner-medium); }
.slot { width: 100%; height: 100%; -webkit-touch-callout: none; user-select: none; }
.more { display: flex; justify-content: center; padding: var(--app-space-4); }
</style>
