<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { fileUrl, thumbUrl } from '@/api/client';
import type { ImageItem } from '@/api/types';
import { useImageActions, type ActionId } from '@/components/imageActions';
import type { GridEntry } from '@/components/gridKeyboard';
import InfoPanel from '@/components/InfoPanel.vue';
import { useI18n } from '@/i18n';
import { useDialogsStore } from '@/stores/dialogs';
import { type ShortcutAction, usePreferencesStore } from '@/stores/preferences';
import { useViewerStore } from '@/stores/viewer';
import { useWindowClass } from '@/theme/breakpoints';
import { formatBytes } from '@/format';
import { AppButton, AppIcon, AppMenu, ContextMenu, IconButton, ProgressCircle, icons, type MenuItem } from '@/ui';

/**
 * The full-screen viewer over whichever list opened it. ← → walk that list and fetch its next page
 * at the end; the wheel, a pinch or a double-click zooms, dragging pans; the information panel is a
 * resizable side sheet, or a bottom sheet on a phone.
 */
const viewer = useViewerStore();
const prefs = usePreferencesStore();
const dialogs = useDialogsStore();
const actions = useImageActions();
const { t } = useI18n();
const windowClass = useWindowClass();
const compact = computed(() => windowClass.value === 'compact');

const item = computed(() => viewer.current);
const src = computed(() => (item.value ? fileUrl(item.value.rootId, item.value.path, item.value.version) : ''));
const isImage = computed(() => item.value?.kind === 'image');

// -- video and audio: opening one starts it from the beginning, with sound ------------------------

const media = ref<HTMLMediaElement | null>(null);
watch(media, (el) => {
  if (!el) return;
  el.currentTime = 0;
  el.muted = false;
  // A browser that refuses sound without a click on the page gets it muted rather than stopped.
  el.play().catch((e: DOMException) => {
    if (e?.name !== 'NotAllowedError') return;
    el.muted = true;
    el.play().catch(() => undefined);
  });
});

// -- other files: a plain-text preview of small text files ------------------------------------------

const TEXT_EXTENSIONS = new Set(['txt', 'json', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'csv', 'tsv', 'md', 'log', 'xml', 'py', 'js', 'ts', 'sh', 'bat']);
const PREVIEW_BYTES = 512 * 1024;
const preview = ref<string | null>(null);
watch(
  () => [item.value?.key, src.value] as const,
  async () => {
    preview.value = null;
    const current = item.value;
    const ext = current?.name.split('.').pop()?.toLowerCase() ?? '';
    if (!current || current.kind !== 'file' || !TEXT_EXTENSIONS.has(ext) || current.size > PREVIEW_BYTES) return;
    const url = src.value;
    try {
      const text = await (await fetch(url)).text();
      if (src.value === url) preview.value = text;
    } catch {
      /* the card still offers the download */
    }
  },
  { immediate: true },
);
const stage = ref<HTMLElement | null>(null);
const natural = reactive({ w: 0, h: 0 });
const view = reactive({ fit: true, scale: 1, x: 0, y: 0 });
const stageSize = reactive({ w: 0, h: 0 });
const loaded = ref(false);
const failed = ref(false);
const menu = reactive({ open: false, x: 0, y: 0 });

const fitScale = computed(() => (natural.w && stageSize.w ? Math.min(stageSize.w / natural.w, stageSize.h / natural.h, 1) : 1));
const scale = computed(() => (view.fit ? fitScale.value : view.scale));
const imageStyle = computed(() => {
  const s = scale.value;
  const left = stageSize.w / 2 + view.x - (natural.w * s) / 2;
  const top = stageSize.h / 2 + view.y - (natural.h * s) / 2;
  return { width: `${natural.w}px`, height: `${natural.h}px`, transform: `translate(${left}px, ${top}px) scale(${s})` };
});
const zoomLabel = computed(() => `${Math.round(scale.value * 100)}%`);

function measure() {
  if (!stage.value) return;
  stageSize.w = stage.value.clientWidth;
  stageSize.h = stage.value.clientHeight;
}
let resize: ResizeObserver | null = null;
watch(stage, (el) => {
  resize?.disconnect();
  if (el) {
    resize = new ResizeObserver(measure);
    resize.observe(el);
    measure();
  }
});

watch(
  () => item.value?.key,
  () => {
    view.fit = true;
    view.x = view.y = 0;
    loaded.value = false;
    failed.value = false;
    preload();
  },
);

function onLoad(event: Event) {
  const img = event.target as HTMLImageElement;
  natural.w = img.naturalWidth;
  natural.h = img.naturalHeight;
  loaded.value = true;
  measure();
}

function preload() {
  const i = viewer.index;
  for (const neighbour of [viewer.items[i + 1], viewer.items[i - 1]]) {
    if (neighbour?.kind === 'image') new Image().src = fileUrl(neighbour.rootId, neighbour.path, neighbour.version);
  }
}

// -- zoom and pan ---------------------------------------------------------------------------------

function zoomAt(next: number, px = stageSize.w / 2, py = stageSize.h / 2) {
  const clamped = Math.min(16, Math.max(0.05, next));
  const s = scale.value;
  const left = stageSize.w / 2 + view.x - (natural.w * s) / 2;
  const top = stageSize.h / 2 + view.y - (natural.h * s) / 2;
  const qx = (px - left) / s;
  const qy = (py - top) / s;
  view.fit = false;
  view.scale = clamped;
  view.x = px - qx * clamped - stageSize.w / 2 + (natural.w * clamped) / 2;
  view.y = py - qy * clamped - stageSize.h / 2 + (natural.h * clamped) / 2;
}
const fit = () => Object.assign(view, { fit: true, x: 0, y: 0 });
const actual = (px?: number, py?: number) => zoomAt(1, px, py);

function onWheel(event: WheelEvent) {
  if (!isImage.value) return;
  event.preventDefault();
  const rect = stage.value!.getBoundingClientRect();
  zoomAt(scale.value * Math.pow(1.0015, -event.deltaY), event.clientX - rect.left, event.clientY - rect.top);
}

function onDoubleClick(event: MouseEvent) {
  if (!isImage.value) return;
  const rect = stage.value!.getBoundingClientRect();
  if (view.fit || Math.abs(scale.value - fitScale.value) < 0.01) actual(event.clientX - rect.left, event.clientY - rect.top);
  else fit();
}

const pointers = new Map<number, { x: number; y: number }>();
let pinchStart: { distance: number; scale: number; cx: number; cy: number } | null = null;
let panStart: { x: number; y: number; vx: number; vy: number } | null = null;
let swipeStart: { x: number; y: number } | null = null;

function onPointerDown(event: PointerEvent) {
  // A player's controls and a file card keep their own pointer: no pan, pinch or swipe there.
  if (event.button !== 0 || (event.target as HTMLElement).closest('video, audio, .file-card')) return;
  (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    const rect = stage.value!.getBoundingClientRect();
    pinchStart = { distance: Math.hypot(a.x - b.x, a.y - b.y), scale: scale.value, cx: (a.x + b.x) / 2 - rect.left, cy: (a.y + b.y) / 2 - rect.top };
    panStart = null;
  } else {
    panStart = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y };
    swipeStart = view.fit ? { x: event.clientX, y: event.clientY } : null;
  }
}

function onPointerMove(event: PointerEvent) {
  if (!pointers.has(event.pointerId)) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pinchStart && pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    zoomAt((pinchStart.scale * Math.hypot(a.x - b.x, a.y - b.y)) / pinchStart.distance, pinchStart.cx, pinchStart.cy);
  } else if (panStart && !view.fit) {
    view.x = panStart.vx + event.clientX - panStart.x;
    view.y = panStart.vy + event.clientY - panStart.y;
  }
}

function onPointerUp(event: PointerEvent) {
  pointers.delete(event.pointerId);
  if (pointers.size < 2) pinchStart = null;
  if (swipeStart && pointers.size === 0) {
    const dx = event.clientX - swipeStart.x;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(event.clientY - swipeStart.y)) (dx < 0 ? viewer.next : viewer.previous)();
  }
  swipeStart = null;
  panStart = null;
}

// -- actions ------------------------------------------------------------------------------------------

const entry = (i: ImageItem): GridEntry => ({ kind: 'image', key: i.key, item: i });
const favorite = computed(() => (item.value ? actions.isFavorite(item.value) : false));

function run(id: ActionId) {
  const current = item.value;
  if (!current) return;
  if (id === 'delete') {
    const before = [...viewer.items];
    dialogs.openDelete([{ root_id: current.rootId, path: current.path }], () => viewer.removed(current.key, before));
    return;
  }
  if (id === 'open') return;
  actions.run(id, [entry(current)]);
}

const menuItems = computed<(MenuItem & { divider?: boolean })[]>(() => (item.value ? actions.menuFor([entry(item.value)]).filter((m) => m.id !== 'open') : []));
// What the framing application takes ("Send to txt2img", "Open workflow"); empty on its own.
const sendItems = computed(() => (item.value ? actions.sendItems(item.value) : []));
function openMenu(event: MouseEvent) {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  Object.assign(menu, { open: true, x: rect.right - 220, y: rect.bottom });
}

// -- slideshow --------------------------------------------------------------------------------------

const playing = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;
watch(playing, (on) => {
  clearInterval(timer);
  if (on) timer = setInterval(() => viewer.next(), Math.max(1, prefs.prefs.slideshowSeconds) * 1000);
});

// -- keyboard -----------------------------------------------------------------------------------------

function matches(action: ShortcutAction, event: KeyboardEvent): boolean {
  const key = prefs.prefs.shortcuts[action];
  return !!key && (event.key === key || event.key.toLowerCase() === key.toLowerCase());
}

function onKey(event: KeyboardEvent) {
  if (!viewer.open || dialogs.transfer || dialogs.rename || dialogs.remove || dialogs.tags || menu.open) return;
  const target = event.target as HTMLElement | null;
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const handled = () => event.preventDefault();
  if (event.key === 'Escape') {
    playing.value ? (playing.value = false) : viewer.close();
    handled();
  } else if (matches('next', event) || event.key === 'ArrowDown' || event.key === 'PageDown') {
    viewer.next();
    handled();
  } else if (matches('previous', event) || event.key === 'ArrowUp' || event.key === 'PageUp') {
    viewer.previous();
    handled();
  } else if (matches('toggleInfo', event)) {
    prefs.prefs.infoOpen = !prefs.prefs.infoOpen;
    handled();
  } else if (matches('favorite', event)) {
    run(favorite.value ? 'unfavorite' : 'favorite');
    handled();
  } else if (matches('delete', event)) {
    run('delete');
    handled();
  } else if (matches('download', event)) {
    run('download');
    handled();
  } else if (matches('copyPrompt', event)) {
    run('copyPrompt');
    handled();
  } else if (matches('slideshow', event)) {
    playing.value = !playing.value;
    handled();
  } else if (!isImage.value) {
    return;
  } else if (event.key === '+' || event.key === '=') {
    zoomAt(scale.value * 1.25);
    handled();
  } else if (event.key === '-') {
    zoomAt(scale.value / 1.25);
    handled();
  } else if (event.key === '0') {
    fit();
    handled();
  } else if (event.key === '1') {
    actual();
    handled();
  }
}

watch(
  () => viewer.open,
  async (open) => {
    if (open) {
      document.addEventListener('keydown', onKey);
      document.body.style.overflow = 'hidden';
      await nextTick();
      measure();
      preload();
    } else {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      playing.value = false;
    }
  },
);
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey);
  clearInterval(timer);
  resize?.disconnect();
});

// -- info panel width -------------------------------------------------------------------------------

function startResize(event: PointerEvent) {
  const startX = event.clientX;
  const startWidth = prefs.prefs.infoWidth;
  const move = (e: PointerEvent) => (prefs.prefs.infoWidth = Math.min(Math.max(300, startWidth + startX - e.clientX), Math.max(320, window.innerWidth * 0.6)));
  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

const strip = computed(() => {
  const i = viewer.index;
  const from = Math.max(0, i - 12);
  return viewer.items.slice(from, i + 13).map((x) => ({ item: x, current: x.key === item.value?.key }));
});
</script>

<template>
  <Teleport to="body">
    <Transition name="scrim">
      <div v-if="viewer.open && item" class="viewer" :class="{ compact, 'with-info': prefs.prefs.infoOpen }" role="dialog" aria-modal="true" :aria-label="item.name">
        <header class="bar">
          <IconButton :icon="icons.X" :label="t('viewer.close')" @click="viewer.close()" />
          <div class="title">
            <span class="type-title-medium name">{{ item.name }}</span>
            <span class="type-body-small dim">{{ t('viewer.position', { index: viewer.index + 1, total: viewer.items.length }) }}<template v-if="viewer.loading"> · {{ t('viewer.loadingMore') }}</template></span>
          </div>
          <template v-if="isImage">
            <span v-if="!compact" class="type-label-medium dim zoom">{{ zoomLabel }}</span>
            <IconButton v-if="!compact" :icon="icons.ZoomOut" :label="t('viewer.zoomOut')" @click="zoomAt(scale / 1.25)" />
            <IconButton v-if="!compact" :icon="icons.ZoomIn" :label="t('viewer.zoomIn')" @click="zoomAt(scale * 1.25)" />
            <IconButton :icon="icons.Maximize2" :label="view.fit ? t('viewer.actual') : t('viewer.fit')" @click="view.fit ? actual() : fit()" />
          </template>
          <!-- Beside a player a ▶ would read as "play this"; the slideshow key still works there. -->
          <IconButton v-if="isImage || playing" :icon="playing ? icons.Pause : icons.Play" :label="t('viewer.slideshow')" @click="playing = !playing" />
          <IconButton v-if="isImage" :icon="icons.Heart" :label="t('viewer.favorite')" :class="{ fav: favorite }" @click="run(favorite ? 'unfavorite' : 'favorite')" />
          <AppMenu v-if="sendItems.length" :items="sendItems" align="end" @select="run($event as ActionId)">
            <template #default="{ toggle }"><IconButton :icon="icons.Send" :label="t('send.menu')" @click="toggle" /></template>
          </AppMenu>
          <IconButton v-if="!compact" :icon="icons.Download" :label="t('common.download')" @click="run('download')" />
          <IconButton v-if="!compact" :icon="icons.Trash2" :label="t('common.delete')" @click="run('delete')" />
          <IconButton :icon="icons.Info" :label="t('viewer.info')" :tonal="prefs.prefs.infoOpen" @click="prefs.prefs.infoOpen = !prefs.prefs.infoOpen" />
          <IconButton :icon="icons.MoreVertical" :label="t('common.more')" @click="openMenu" />
        </header>

        <div class="main">
          <div
            ref="stage"
            class="stage"
            :class="{ zoomed: !view.fit, 'not-image': !isImage }"
            @wheel="onWheel"
            @dblclick="onDoubleClick"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerUp"
            @contextmenu.prevent="Object.assign(menu, { open: true, x: $event.clientX, y: $event.clientY })"
          >
            <template v-if="item.kind === 'image'">
              <img v-if="!failed" :key="src" :src="src" class="image" :class="{ loaded }" :style="imageStyle" alt="" draggable="false" @load="onLoad" @error="failed = true" />
              <img v-if="!loaded && !failed" :src="thumbUrl(item.rootId, item.path, item.version, 512)" class="placeholder" alt="" draggable="false" />
              <ProgressCircle v-if="!loaded && !failed" class="spinner" :size="36" />
              <div v-if="failed" class="failed dim type-body-large"><AppIcon :icon="icons.ImageOff" /> {{ t('viewer.notAnImage') }}</div>
            </template>
            <video v-else-if="item.kind === 'video'" ref="media" :key="src" :src="src" class="media" controls playsinline />
            <div v-else class="file-card" :class="{ wide: preview !== null }">
              <span class="file-icon"><AppIcon :icon="item.kind === 'audio' ? icons.Music : icons.File" /></span>
              <span class="type-title-medium file-name">{{ item.name }}</span>
              <span class="type-body-small dim">{{ formatBytes(item.size) }}</span>
              <audio v-if="item.kind === 'audio'" ref="media" :key="src" :src="src" class="audio" controls />
              <template v-else>
                <pre v-if="preview !== null" class="file-preview type-body-small">{{ preview }}</pre>
                <p v-else class="type-body-medium dim">{{ t('viewer.notAnImage') }}</p>
                <AppButton :icon="icons.Download" @click="run('download')">{{ t('common.download') }}</AppButton>
              </template>
            </div>

            <button v-if="viewer.index > 0" type="button" class="nav prev" :aria-label="t('viewer.previous')" @click.stop="viewer.previous()" @pointerdown.stop>
              <AppIcon :icon="icons.ChevronLeft" />
            </button>
            <button v-if="viewer.index < viewer.items.length - 1 || viewer.source?.hasMore?.()" type="button" class="nav next" :aria-label="t('viewer.next')" @click.stop="viewer.next()" @pointerdown.stop>
              <AppIcon :icon="icons.ChevronRight" />
            </button>
          </div>

          <Transition name="sheet">
            <aside v-if="prefs.prefs.infoOpen" class="info" :style="compact ? undefined : { width: `${prefs.prefs.infoWidth}px` }">
              <div v-if="!compact" class="resize" role="separator" aria-orientation="vertical" @pointerdown.prevent="startResize" />
              <InfoPanel :item="item" :previous="viewer.previousItem" />
            </aside>
          </Transition>
        </div>

        <nav v-if="!compact" class="strip" :aria-label="t('viewer.filmstrip')">
          <button v-for="s in strip" :key="s.item.key" type="button" class="frame" :class="{ current: s.current }" :aria-label="s.item.name" @click="viewer.goTo(s.item.key)">
            <img v-if="s.item.kind === 'image'" :src="thumbUrl(s.item.rootId, s.item.path, s.item.version, 128)" alt="" loading="lazy" draggable="false" />
            <video v-else-if="s.item.kind === 'video'" :src="`${fileUrl(s.item.rootId, s.item.path, s.item.version)}#t=0.1`" muted preload="metadata" tabindex="-1" />
            <AppIcon v-else :icon="s.item.kind === 'audio' ? icons.Music : icons.File" :size="20" />
          </button>
        </nav>
        <ContextMenu v-model:open="menu.open" :items="menuItems" :x="menu.x" :y="menu.y" @select="run($event as ActionId)" />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.viewer {
  position: fixed; inset: 0; z-index: 45; display: flex; flex-direction: column;
  background: color-mix(in srgb, var(--md-sys-color-scrim) 94%, var(--md-sys-color-surface)); color: var(--md-sys-color-inverse-on-surface);
  --md-icon-button-icon-color: var(--md-sys-color-inverse-on-surface);
  --md-icon-button-hover-icon-color: var(--md-sys-color-inverse-on-surface);
}
.bar { display: flex; align-items: center; gap: var(--app-space-1); min-height: 56px; padding: 0 var(--app-space-2); }
.title { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dim { opacity: 0.72; }
.zoom { min-width: 48px; text-align: right; }
.fav { color: var(--md-sys-color-error); --md-icon-button-icon-color: var(--md-sys-color-error); }
.main { flex: 1; min-height: 0; display: flex; }
.stage { position: relative; flex: 1; min-width: 0; overflow: hidden; touch-action: none; cursor: zoom-in; user-select: none; }
.stage.zoomed { cursor: grab; }
.stage.zoomed:active { cursor: grabbing; }
.image { position: absolute; top: 0; left: 0; transform-origin: 0 0; opacity: 0; transition: opacity var(--md-sys-motion-duration-short4) var(--md-sys-motion-easing-standard); }
.image.loaded { opacity: 1; }
.placeholder { position: absolute; inset: 0; margin: auto; max-width: 100%; max-height: 100%; object-fit: contain; filter: blur(2px); }
.spinner { position: absolute; left: 50%; top: 50%; translate: -50% -50%; }
.media { position: absolute; inset: 0; margin: auto; max-width: 100%; max-height: 100%; }
.stage.not-image { cursor: default; touch-action: auto; }
/* Audio and other files: a card in the middle of the stage. */
.file-card {
  position: absolute; inset: 0; margin: auto; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--app-space-2);
  width: min(var(--app-width-dialog-small), calc(100% - 32px)); height: fit-content; max-height: calc(100% - 32px); padding: var(--app-space-6);
  border-radius: var(--md-sys-shape-corner-extra-large); background: var(--md-sys-color-surface-container); color: var(--md-sys-color-on-surface); user-select: text;
}
.file-card.wide { width: min(var(--app-width-dialog-medium), calc(100% - 32px)); }
.file-icon {
  display: grid; place-items: center; width: 72px; height: 72px; border-radius: var(--md-sys-shape-corner-large);
  background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container);
}
.file-name { max-width: 100%; min-width: 0; overflow-wrap: anywhere; text-align: center; }
.audio { width: 100%; margin-top: var(--app-space-2); }
.file-preview {
  align-self: stretch; min-height: 0; max-height: 50vh; margin: var(--app-space-2) 0; padding: var(--app-space-3); overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere;
  border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container-high); font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.failed { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; gap: var(--app-space-2); }
.nav {
  position: absolute; top: 50%; translate: 0 -50%; display: grid; place-items: center; width: 48px; height: 96px; border: 0; cursor: pointer;
  background: color-mix(in srgb, var(--md-sys-color-scrim) 40%, transparent); color: var(--md-sys-color-inverse-on-surface);
  opacity: 0; transition: opacity var(--md-sys-motion-duration-short4) var(--md-sys-motion-easing-standard);
}
.stage:hover .nav, .nav:focus-visible { opacity: 1; }
.prev { left: 0; border-radius: 0 var(--md-sys-shape-corner-large) var(--md-sys-shape-corner-large) 0; }
.next { right: 0; border-radius: var(--md-sys-shape-corner-large) 0 0 var(--md-sys-shape-corner-large); }
.info {
  position: relative; flex: none; min-width: min(300px, 100%); max-width: 70vw; display: flex; flex-direction: column;
  background: var(--md-sys-color-surface-container-low); color: var(--md-sys-color-on-surface); border-radius: var(--md-sys-shape-corner-large) 0 0 0;
  /* The panel is a light surface inside the dark viewer: its icons take the surface's colours again. */
  --md-icon-button-icon-color: var(--md-sys-color-on-surface-variant);
  --md-icon-button-hover-icon-color: var(--md-sys-color-on-surface);
}
.resize { position: absolute; left: -4px; top: 0; bottom: 0; width: 8px; cursor: col-resize; z-index: 1; }
.resize:hover { background: color-mix(in srgb, var(--md-sys-color-primary) 30%, transparent); }
.strip { display: flex; gap: var(--app-space-1); justify-content: center; height: 72px; padding: var(--app-space-2); overflow: hidden; }
.frame { flex: none; width: 56px; height: 56px; padding: 0; border: 2px solid transparent; border-radius: var(--md-sys-shape-corner-small); overflow: hidden; background: var(--md-sys-color-surface-container-highest); cursor: pointer; opacity: 0.6; display: grid; place-items: center; color: var(--md-sys-color-on-surface-variant); }
.frame.current { border-color: var(--md-sys-color-primary); opacity: 1; }
.frame img, .frame video { width: 100%; height: 100%; object-fit: cover; pointer-events: none; }
.compact .main { flex-direction: column; }
.compact .info { max-width: none; min-width: 0; height: 55%; border-radius: var(--md-sys-shape-corner-extra-large) var(--md-sys-shape-corner-extra-large) 0 0; padding-bottom: env(safe-area-inset-bottom); }
.compact .nav { opacity: 1; width: 40px; height: 64px; }
</style>
