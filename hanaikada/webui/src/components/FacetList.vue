<script setup lang="ts">
import { computed, ref } from 'vue';
import type { FacetValue } from '@/api/types';
import { useI18n } from '@/i18n';
import { Chip } from '@/ui';

/** Selectable values with their counts: platforms, models, samplers. Long lists fold after a few. */
const props = withDefaults(defineProps<{ label: string; values: FacetValue[]; format?: (v: string) => string; fold?: number }>(), { fold: 8 });
const model = defineModel<string[]>({ default: () => [] });
const { t } = useI18n();
const expanded = ref(false);
const shown = computed(() => {
  const selectedMissing = model.value.filter((v) => !props.values.some((f) => f.value === v)).map((value) => ({ value, count: 0 }));
  const all = [...props.values, ...selectedMissing];
  return expanded.value ? all : all.slice(0, props.fold);
});
const toggle = (value: string) => (model.value = model.value.includes(value) ? model.value.filter((v) => v !== value) : [...model.value, value]);
</script>

<template>
  <fieldset v-if="values.length || model.length" class="facet">
    <legend class="type-label-large muted">{{ label }}</legend>
    <div class="chips">
      <Chip v-for="f in shown" :key="f.value" :label="format ? format(f.value) : f.value" :count="f.count || null" :selected="model.includes(f.value)" @click="toggle(f.value)" />
      <button v-if="values.length > fold" type="button" class="more type-label-large" @click="expanded = !expanded">{{ expanded ? '−' : `+${values.length - fold}` }} {{ expanded ? '' : t('common.more') }}</button>
    </div>
  </fieldset>
</template>

<style scoped>
.facet { margin: 0; padding: 0; border: 0; min-width: 0; }
legend { padding: 0 0 var(--app-space-1); }
.chips { display: flex; flex-wrap: wrap; gap: var(--app-space-1); }
.more { border: 0; background: transparent; color: var(--md-sys-color-primary); cursor: pointer; font: inherit; padding: 0 var(--app-space-2); }
</style>
