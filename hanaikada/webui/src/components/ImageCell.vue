<script setup lang="ts">
import { computed, ref } from 'vue';
import { fileUrl, thumbUrl } from '@/api/client';
import type { ImageItem } from '@/api/types';
import { thumbSizeFor } from '@/components/gridKeyboard';
import PlatformBadge from '@/components/PlatformBadge.vue';
import VideoThumb from '@/components/VideoThumb.vue';
import { formatDuration } from '@/format';
import { useI18n } from '@/i18n';
import { usePreferencesStore } from '@/stores/preferences';
import { AppIcon, icons } from '@/ui';

/**
 * One file in a grid: an image's lazily loaded thumbnail (a video's own frames, see VideoThumb; an
 * icon for anything else), its name, the platform that made it, dots for its custom tags, a
 * shimmer while it is not indexed yet, and a blur when a blur tag applies.
 */
const props = defineProps<{ item: ImageItem; size: number; showName: boolean; selected: boolean; focused: boolean; tagColors: Map<number, string | null>; blurred?: boolean; favoriteId?: number | null }>();
const emit = defineEmits<{ toggleSelect: [MouseEvent] }>();
const { t } = useI18n();
const prefs = usePreferencesStore();
const failed = ref(false);
const duration = ref<number | null>(null);
const loaded = ref(false);

const src = computed(() => (props.item.kind === 'image' ? thumbUrl(props.item.rootId, props.item.path, props.item.version, thumbSizeFor(props.size)) : null));
const video = computed(() => (props.item.kind === 'video' ? fileUrl(props.item.rootId, props.item.path, props.item.version) : null));
const dots = computed(() => (props.item.image?.tag_ids ?? []).filter((id) => id !== props.favoriteId).slice(0, 5));
const favorite = computed(() => props.favoriteId != null && (props.item.image?.tag_ids ?? []).includes(props.favoriteId));
const fileIcon = computed(() => ({ video: icons.Film, audio: icons.Music })[props.item.kind as 'video' | 'audio'] ?? icons.File);
const ext = computed(() => props.item.name.split('.').pop()?.toUpperCase() ?? '');
</script>

<template>
  <div class="cell" :class="{ selected, focused, blurred }" :title="item.name">
    <div class="thumb">
      <img v-if="src && !failed" :src="src" alt="" loading="lazy" decoding="async" draggable="false" :class="{ loaded }" @load="loaded = true" @error="failed = true" />
      <VideoThumb v-else-if="video && !failed" :src="video" :play="prefs.prefs.videoAutoplay" @error="failed = true" @duration="duration = $event" />
      <div v-else class="placeholder">
        <AppIcon :icon="item.kind === 'image' ? icons.ImageOff : fileIcon" :size="24" />
        <span v-if="item.kind !== 'image'" class="type-label-small">{{ ext }}</span>
      </div>
      <button type="button" class="check" :class="{ on: selected }" :aria-label="t('selection.selectAll')" :aria-pressed="selected" @click.stop="emit('toggleSelect', $event)">
        <AppIcon :icon="selected ? icons.SquareCheck : icons.Square" :size="20" />
      </button>
      <div class="badges">
        <span v-if="item.kind === 'video'" class="media-badge type-label-small"><AppIcon :icon="icons.Film" :size="18" />{{ duration != null ? formatDuration(duration) : '' }}</span>
        <PlatformBadge :platform="item.image?.platform" />
        <span v-if="item.image?.has_error" class="error-mark" :title="t('common.error')"><AppIcon :icon="icons.AlertTriangle" :size="18" /></span>
      </div>
      <div class="marks">
        <AppIcon v-if="favorite" :icon="icons.Heart" :size="18" class="heart" />
        <span v-for="id in dots" :key="id" class="dot" :style="{ background: tagColors.get(id) ?? undefined }" />
      </div>
      <div v-if="item.kind === 'image' && !item.indexed" class="shimmer" :title="t('browse.notIndexed')" />
    </div>
    <div v-if="showName" class="caption type-body-small">{{ item.name }}</div>
  </div>
</template>

<style scoped>
.cell { display: flex; flex-direction: column; width: 100%; height: 100%; border-radius: var(--md-sys-shape-corner-medium); cursor: pointer; }
.thumb {
  position: relative; flex: none; aspect-ratio: 1; overflow: hidden; border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-highest);
}
img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0; transition: opacity var(--md-sys-motion-duration-short4) var(--md-sys-motion-easing-standard), filter var(--md-sys-motion-duration-medium1) var(--md-sys-motion-easing-standard); }
img.loaded { opacity: 1; }
.blurred img { filter: blur(18px) saturate(0.7); }
.blurred:hover img { filter: none; }
.placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--app-space-1); height: 100%; color: var(--md-sys-color-on-surface-variant); }
.cell:hover .thumb::after, .focused .thumb::after {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background: color-mix(in srgb, var(--md-sys-color-on-surface) calc(var(--md-sys-state-hover-state-layer-opacity) * 100%), transparent);
}
.focused .thumb { outline: 2px solid var(--md-sys-color-secondary); outline-offset: -2px; }
.selected .thumb { outline: 3px solid var(--md-sys-color-primary); outline-offset: -3px; }
.check {
  position: absolute; top: var(--app-space-1); left: var(--app-space-1); display: grid; place-items: center; width: 28px; height: 28px;
  padding: 0; border: 0; border-radius: var(--md-sys-shape-corner-small); cursor: pointer; opacity: 0;
  background: color-mix(in srgb, var(--md-sys-color-surface) 80%, transparent); color: var(--md-sys-color-on-surface);
  transition: opacity var(--md-sys-motion-duration-short3) var(--md-sys-motion-easing-standard);
}
.cell:hover .check, .check.on, .check:focus-visible { opacity: 1; }
.check.on { background: var(--md-sys-color-primary); color: var(--md-sys-color-on-primary); }
.badges { position: absolute; left: var(--app-space-1); bottom: var(--app-space-1); display: flex; gap: var(--app-space-1); }
.media-badge {
  display: inline-flex; align-items: center; gap: 2px; height: 20px; padding: 0 var(--app-space-1) 0 2px; border-radius: var(--md-sys-shape-corner-extra-small);
  background: color-mix(in srgb, var(--md-sys-color-surface) 80%, transparent); color: var(--md-sys-color-on-surface);
}
.blurred :deep(.video-thumb) { filter: blur(18px) saturate(0.7); }
.blurred:hover :deep(.video-thumb) { filter: none; }
.error-mark { display: grid; place-items: center; width: 20px; height: 20px; border-radius: var(--md-sys-shape-corner-extra-small); background: var(--md-sys-color-error-container); color: var(--md-sys-color-on-error-container); }
.marks { position: absolute; right: var(--app-space-1); bottom: var(--app-space-1); display: flex; align-items: center; gap: 3px; }
.heart { color: var(--md-sys-color-error); fill: currentColor; filter: drop-shadow(0 0 2px var(--md-sys-color-surface)); }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--md-sys-color-tertiary); box-shadow: 0 0 0 2px var(--md-sys-color-surface); }
.shimmer {
  position: absolute; left: 0; right: 0; bottom: 0; height: 3px;
  background: linear-gradient(90deg, transparent, var(--md-sys-color-primary), transparent); background-size: 200% 100%;
  animation: shimmer 1.4s linear infinite;
}
@keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
.caption { min-width: 0; padding: var(--app-space-1) var(--app-space-1) 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--md-sys-color-on-surface-variant); }
</style>
