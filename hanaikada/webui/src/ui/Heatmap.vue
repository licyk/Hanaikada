<script setup lang="ts">
import { computed } from 'vue';

/**
 * A contribution heatmap: one square per day for the last ``weeks`` weeks, darker for more. Plain
 * SVG, coloured from the primary role, so it follows the theme.
 */
const props = withDefaults(defineProps<{ days: { day: string; count: number }[]; weeks?: number; end?: string; label?: string; dayNames?: string[] }>(), { weeks: 53 });
const CELL = 12;
const GAP = 3;
const LEFT = 28;
const TOP = 16;

const counts = computed(() => new Map(props.days.map((d) => [d.day, d.count])));
const max = computed(() => Math.max(1, ...props.days.map((d) => d.count)));

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const cells = computed(() => {
  const endDay = props.end ? new Date(`${props.end}T00:00:00`) : new Date();
  endDay.setHours(0, 0, 0, 0);
  const start = new Date(endDay);
  start.setDate(start.getDate() - (props.weeks - 1) * 7 - endDay.getDay());
  const out: { x: number; y: number; day: string; count: number; level: number }[] = [];
  for (let d = new Date(start), i = 0; d <= endDay; d.setDate(d.getDate() + 1), i++) {
    const day = iso(d);
    const count = counts.value.get(day) ?? 0;
    const level = count === 0 ? 0 : Math.min(4, Math.ceil((count / max.value) * 4));
    out.push({ x: LEFT + Math.floor(i / 7) * (CELL + GAP), y: TOP + d.getDay() * (CELL + GAP), day, count, level });
  }
  return out;
});

const months = computed(() => {
  const out: { x: number; label: string }[] = [];
  let last = '';
  for (const c of cells.value) {
    const month = c.day.slice(0, 7);
    if (month !== last && c.y === TOP) {
      out.push({ x: c.x, label: month.slice(5) });
      last = month;
    }
  }
  return out;
});

const width = computed(() => LEFT + props.weeks * (CELL + GAP));
const height = TOP + 7 * (CELL + GAP);
</script>

<template>
  <svg class="heatmap" :viewBox="`0 0 ${width} ${height}`" :style="{ minWidth: `${width}px`, maxWidth: `${width * 1.8}px` }" role="img" :aria-label="label">
    <text v-for="m in months" :key="m.x" :x="m.x" y="10" class="axis">{{ m.label }}</text>
    <text v-for="(name, i) in dayNames ?? []" v-show="i % 2 === 1" :key="name" x="0" :y="TOP + i * (CELL + GAP) + CELL - 2" class="axis">{{ name }}</text>
    <rect v-for="c in cells" :key="c.day" :x="c.x" :y="c.y" :width="CELL" :height="CELL" rx="2" :class="`level-${c.level}`">
      <title>{{ c.day }}: {{ c.count }}</title>
    </rect>
  </svg>
</template>

<style scoped>
/* Fills the card: never smaller than one pixel per unit (the card scrolls instead), never so large a year of days turns into tiles. */
.heatmap { display: block; width: 100%; height: auto; }
.axis { font-size: 9px; fill: var(--md-sys-color-on-surface-variant); }
.level-0 { fill: var(--md-sys-color-surface-container-highest); }
.level-1 { fill: color-mix(in srgb, var(--md-sys-color-primary) 30%, var(--md-sys-color-surface-container-highest)); }
.level-2 { fill: color-mix(in srgb, var(--md-sys-color-primary) 55%, var(--md-sys-color-surface-container-highest)); }
.level-3 { fill: color-mix(in srgb, var(--md-sys-color-primary) 78%, var(--md-sys-color-surface-container-highest)); }
.level-4 { fill: var(--md-sys-color-primary); }
</style>
