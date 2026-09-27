<script setup lang="ts">
import TextField from '@/ui/TextField.vue';

/** A numeric range: two fields, either end may be empty. The model is ``[min, max]``. */
defineProps<{ label: string; minLabel: string; maxLabel: string; step?: number }>();
const model = defineModel<[number | null, number | null]>({ default: () => [null, null] });

function set(i: 0 | 1, value: string | number | null) {
  const next: [number | null, number | null] = [...model.value];
  next[i] = value === '' || value === null ? null : Number(value);
  model.value = next;
}
</script>

<template>
  <fieldset class="range">
    <legend class="type-label-large muted">{{ label }}</legend>
    <TextField :model-value="model[0] ?? ''" type="number" :label="minLabel" @update:model-value="set(0, $event)" />
    <span class="muted">–</span>
    <TextField :model-value="model[1] ?? ''" type="number" :label="maxLabel" @update:model-value="set(1, $event)" />
  </fieldset>
</template>

<style scoped>
.range { display: flex; align-items: center; gap: var(--app-space-2); margin: 0; padding: 0; border: 0; min-width: 0; }
.range > :deep(.text-field) { flex: 1; min-width: 0; }
legend { padding: 0 0 var(--app-space-1); }
</style>
