<script setup lang="ts">
import { computed } from 'vue';
import { thumbUrl } from '@/api/client';
import { type GridFolder, thumbSizeFor } from '@/components/gridKeyboard';
import { AppIcon, icons } from '@/ui';

/** A folder in the grid: a mosaic of its newest images, its name and its layout label. */
const props = defineProps<{ folder: GridFolder; rootId: string; size: number; showName: boolean; selected: boolean; focused: boolean; dropping?: boolean }>();
const tiles = computed(() => props.folder.cover.slice(0, 4));
const name = computed(() => props.folder.display_name ?? props.folder.name);
const tileSize = computed(() => thumbSizeFor(tiles.value.length > 1 ? props.size / 2 : props.size));
</script>

<template>
  <div class="cell" :class="{ selected, focused, dropping }" :title="name">
    <div class="thumb" :class="`n${tiles.length}`">
      <img v-for="c in tiles" :key="c.path" :src="thumbUrl(rootId, c.path, c.version, tileSize)" alt="" loading="lazy" decoding="async" draggable="false" />
      <div class="folder-mark"><AppIcon :icon="icons.Folder" :size="tiles.length ? 20 : 24" /></div>
      <span v-if="folder.label" class="label type-label-small">{{ folder.label }}</span>
    </div>
    <div v-if="showName" class="caption type-body-small">{{ name }}</div>
  </div>
</template>

<style scoped>
.cell { display: flex; flex-direction: column; width: 100%; height: 100%; cursor: pointer; }
.thumb {
  position: relative; aspect-ratio: 1; overflow: hidden; display: grid; gap: 2px; border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container);
}
.n2 { grid-template-columns: 1fr 1fr; }
.n3, .n4 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.n3 img:first-child { grid-row: span 2; }
img { width: 100%; height: 100%; object-fit: cover; display: block; min-height: 0; }
.folder-mark {
  position: absolute; left: var(--app-space-1); bottom: var(--app-space-1); display: grid; place-items: center; width: 32px; height: 32px;
  border-radius: var(--md-sys-shape-corner-small); background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container);
}
.n0 .folder-mark { position: static; width: 100%; height: 100%; border-radius: 0; }
.label {
  position: absolute; top: var(--app-space-1); right: var(--app-space-1); padding: 2px var(--app-space-2); border-radius: var(--md-sys-shape-corner-full);
  background: var(--md-sys-color-tertiary-container); color: var(--md-sys-color-on-tertiary-container);
}
.cell:hover .thumb::after, .focused .thumb::after {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background: color-mix(in srgb, var(--md-sys-color-on-surface) calc(var(--md-sys-state-hover-state-layer-opacity) * 100%), transparent);
}
.focused .thumb { outline: 2px solid var(--md-sys-color-secondary); outline-offset: -2px; }
.selected .thumb, .dropping .thumb { outline: 3px solid var(--md-sys-color-primary); outline-offset: -3px; }
.dropping .thumb::after { content: ''; position: absolute; inset: 0; background: color-mix(in srgb, var(--md-sys-color-primary) calc(var(--md-sys-state-dragged-state-layer-opacity) * 100%), transparent); }
.caption { min-width: 0; padding: var(--app-space-1) var(--app-space-1) 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
</style>
