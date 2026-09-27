<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

/**
 * Vertical bars with a label under each, in plain SVG. Values are counts. The bars share out the
 * width of the container, between a minimum below which it scrolls and a maximum.
 */
const props = withDefaults(defineProps<{ bars: { label: string; value: number }[]; height?: number; label?: string }>(), { height: 160 });
const MIN_SLOT = 30;
const MAX_SLOT = 96; // a few bars stay together instead of spreading across a wide card
const MAX_BAR = 48;
const GAP = 8;
const BOTTOM = 18;
const wrap = ref<HTMLElement | null>(null);
const available = ref(0);
const max = computed(() => Math.max(1, ...props.bars.map((b) => b.value)));
const slot = computed(() => Math.min(MAX_SLOT, Math.max(MIN_SLOT, props.bars.length ? available.value / props.bars.length : 0)));
const bar = computed(() => Math.min(MAX_BAR, slot.value - GAP));
const width = computed(() => Math.max(1, props.bars.length * slot.value));
const scaled = computed(() =>
  props.bars.map((b, i) => {
    const h = Math.round(((props.height - BOTTOM - 14) * b.value) / max.value);
    return { ...b, x: i * slot.value + (slot.value - bar.value) / 2, y: props.height - BOTTOM - h, h };
  }),
);

let observer: ResizeObserver | null = null;
onMounted(() => {
  if (!wrap.value) return;
  available.value = wrap.value.clientWidth;
  if (typeof ResizeObserver === 'undefined') return;
  observer = new ResizeObserver(() => {
    // A kept-alive page that is not shown measures 0; keep the last real width.
    if (wrap.value?.clientWidth) available.value = wrap.value.clientWidth;
  });
  observer.observe(wrap.value);
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div ref="wrap" class="bars-wrap">
    <svg class="bars" :viewBox="`0 0 ${width} ${height}`" :width="width" :height="height" role="img" :aria-label="label">
      <g v-for="b in scaled" :key="b.label">
        <rect :x="b.x" :y="b.y" :width="bar" :height="Math.max(b.h, 1)" rx="4" class="bar"><title>{{ b.label }}: {{ b.value }}</title></rect>
        <text :x="b.x + bar / 2" :y="b.y - 3" class="value">{{ b.value || '' }}</text>
        <text :x="b.x + bar / 2" :y="height - 4" class="axis">{{ b.label }}</text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.bars-wrap { overflow-x: auto; max-width: 100%; }
.bars { display: block; }
.bar { fill: var(--md-sys-color-primary); }
.value, .axis { font-size: 9px; text-anchor: middle; fill: var(--md-sys-color-on-surface-variant); }
</style>
