<script setup lang="ts" generic="T">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useKeepScroll } from '@/ui/useKeepScroll';

/**
 * A virtualised grid of square cells with an optional caption row. Only the rows in view (plus
 * an overscan) are rendered, so a folder of tens of thousands of images scrolls smoothly. Cells
 * are as wide as fits ``minCellWidth`` into the width; ``near-end`` asks the owner for more.
 */
const props = withDefaults(
  defineProps<{ items: T[]; itemKey: (item: T) => string; minCellWidth?: number; gap?: number; captionHeight?: number; overscanRows?: number; endThresholdRows?: number; label?: string }>(),
  { minCellWidth: 200, gap: 8, captionHeight: 0, overscanRows: 3, endThresholdRows: 4 },
);
const emit = defineEmits<{ nearEnd: [] }>();

const scroller = ref<HTMLElement | null>(null);
const width = ref(0);
const height = ref(0);
const scrollTop = ref(0);
let observer: ResizeObserver | null = null;

const columns = computed(() => Math.max(1, Math.floor((width.value + props.gap) / (props.minCellWidth + props.gap))));
const cellWidth = computed(() => Math.max(1, (width.value - props.gap * (columns.value - 1)) / columns.value));
const rowHeight = computed(() => cellWidth.value + props.captionHeight + props.gap);
const rowCount = computed(() => Math.ceil(props.items.length / columns.value));
const totalHeight = computed(() => Math.max(0, rowCount.value * rowHeight.value - props.gap));
const firstRow = computed(() => Math.max(0, Math.floor(scrollTop.value / rowHeight.value) - props.overscanRows));
const lastRow = computed(() => Math.min(rowCount.value - 1, Math.ceil((scrollTop.value + height.value) / rowHeight.value) + props.overscanRows));

const visible = computed(() => {
  const out: { item: T; index: number; style: Record<string, string> }[] = [];
  if (!width.value) return out;
  const start = firstRow.value * columns.value;
  const end = Math.min(props.items.length, (lastRow.value + 1) * columns.value);
  for (let index = start; index < end; index++) {
    const row = Math.floor(index / columns.value);
    const col = index % columns.value;
    out.push({
      item: props.items[index],
      index,
      style: {
        transform: `translate(${col * (cellWidth.value + props.gap)}px, ${row * rowHeight.value}px)`,
        width: `${cellWidth.value}px`,
        height: `${cellWidth.value + props.captionHeight}px`,
      },
    });
  }
  return out;
});

function measure() {
  const el = scroller.value;
  // Out of the document (a kept-alive page not shown) it measures 0: keep the last real size, so
  // the cells stay rendered for when the page comes back.
  if (!el?.clientWidth) return;
  width.value = el.clientWidth;
  height.value = el.clientHeight;
  holdPlace(el);
  checkEnd();
}

// Something opening or closing above the grid (the selection bar) moves the grid's top edge. Once
// scrolled, the offset follows it, so the cells stay where they are on screen and the newcomer
// takes its room from the top of the view; at the very top the cells move down with the edge.
let lastTop: number | null = null;
let carry = 0;
function holdPlace(el: HTMLElement) {
  const top = el.getBoundingClientRect().top;
  const moved = lastTop === null ? 0 : top - lastTop;
  lastTop = top;
  if (!moved || el.scrollTop <= 0) {
    carry = 0;
    return;
  }
  // The offset may land on whole pixels only: what it drops is carried into the next step.
  const want = el.scrollTop + moved + carry;
  el.scrollTop = want;
  carry = Math.abs(want - el.scrollTop) < 1 ? want - el.scrollTop : 0;
}

function onScroll() {
  scrollTop.value = scroller.value?.scrollTop ?? 0;
  checkEnd();
}

function checkEnd() {
  if (!props.items.length) return;
  if (lastRow.value >= rowCount.value - 1 - props.endThresholdRows) emit('nearEnd');
}

/** Scroll so that the item at ``index`` is in view. */
function scrollToIndex(index: number, align: 'nearest' | 'start' = 'nearest') {
  const el = scroller.value;
  if (!el || index < 0) return;
  const top = Math.floor(index / columns.value) * rowHeight.value;
  const bottom = top + rowHeight.value - props.gap;
  if (align === 'start' || top < el.scrollTop) el.scrollTop = top;
  else if (bottom > el.scrollTop + el.clientHeight) el.scrollTop = bottom - el.clientHeight;
}

function scrollToTop() {
  if (scroller.value) scroller.value.scrollTop = 0;
}

watch(() => props.items.length, () => requestAnimationFrame(checkEnd));
useKeepScroll(scroller, () => {
  // Whatever moved while the page was away is not followed.
  lastTop = null;
  measure();
  onScroll();
});
onMounted(() => {
  measure();
  observer = new ResizeObserver(measure);
  if (scroller.value) observer.observe(scroller.value);
});
onBeforeUnmount(() => observer?.disconnect());

defineExpose({ scrollToIndex, scrollToTop, columns, el: scroller });
</script>

<template>
  <div ref="scroller" class="virtual-grid" role="grid" :aria-label="label" :aria-rowcount="rowCount" @scroll.passive="onScroll">
    <div class="spacer" :style="{ height: `${totalHeight}px` }">
      <div v-for="cell in visible" :key="itemKey(cell.item)" class="cell" role="gridcell" :style="cell.style">
        <slot :item="cell.item" :index="cell.index" :width="cellWidth" />
      </div>
    </div>
    <slot name="after" />
  </div>
</template>

<style scoped>
.virtual-grid { position: relative; height: 100%; overflow-y: auto; overflow-x: hidden; contain: strict; scrollbar-gutter: stable; }
.spacer { position: relative; width: 100%; }
.cell { position: absolute; top: 0; left: 0; }
</style>
