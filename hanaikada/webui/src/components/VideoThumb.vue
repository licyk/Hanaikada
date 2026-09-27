<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue';
import { useViewerStore } from '@/stores/viewer';
import { prefersReducedMotion } from '@/ui';

/**
 * A video in a grid cell, drawn by the browser from the file itself (the server makes no video
 * thumbnails). With ``play`` it runs muted and looping, but only while it is on screen and no
 * viewer covers the grid; otherwise, and when the system asks for reduced motion, it shows a
 * still frame from just after the start.
 */
const props = defineProps<{ src: string; play: boolean }>();
const emit = defineEmits<{ error: []; duration: [number] }>();
const el = ref<HTMLVideoElement | null>(null);
const visible = ref(false);
const viewer = useViewerStore();
const moving = computed(() => props.play && visible.value && !viewer.open && !prefersReducedMotion());

let observer: IntersectionObserver | null = null;
function observe() {
  observer?.disconnect();
  if (!el.value || typeof IntersectionObserver === 'undefined') {
    visible.value = true;
    return;
  }
  observer = new IntersectionObserver(([entry]) => (visible.value = !!entry?.isIntersecting), { threshold: 0.1 });
  observer.observe(el.value);
}
onMounted(observe);
// A kept-alive page leaves the document when hidden: stop, and look again when it is back.
onDeactivated(() => {
  observer?.disconnect();
  visible.value = false;
});
onActivated(observe);
onBeforeUnmount(() => observer?.disconnect());

watch(moving, (on) => {
  const video = el.value;
  if (!video) return;
  if (on) video.play().catch(() => undefined);
  else video.pause();
});

function onMetadata() {
  const seconds = el.value?.duration;
  if (seconds && Number.isFinite(seconds)) emit('duration', seconds);
  if (moving.value) el.value?.play().catch(() => undefined);
}
</script>

<template>
  <video
    ref="el"
    class="video-thumb"
    :src="play ? src : `${src}#t=0.1`"
    muted
    loop
    playsinline
    disablepictureinpicture
    disableremoteplayback
    :preload="play ? 'auto' : 'metadata'"
    tabindex="-1"
    draggable="false"
    @loadedmetadata="onMetadata"
    @error="emit('error')"
  />
</template>

<style scoped>
.video-thumb { width: 100%; height: 100%; object-fit: cover; display: block; pointer-events: none; background: var(--md-sys-color-surface-container-highest); }
</style>
