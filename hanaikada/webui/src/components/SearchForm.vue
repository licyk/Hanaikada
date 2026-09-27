<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useRoots } from '@/api/queries/library';
import { useFacets } from '@/api/queries/search';
import type { SearchSort } from '@/api/types';
import FacetList from '@/components/FacetList.vue';
import TagSelect from '@/components/TagSelect.vue';
import { useI18n } from '@/i18n';
import { samplerLabel } from '@/metadata/samplers';
import type { QueryState } from '@/search/url';
import { AppButton, Chip, RangeField, SegmentedButton, SelectField, Switch, TextField, icons } from '@/ui';

type Field = 'prompt' | 'negative' | 'name' | 'model' | 'loras';

/**
 * Every filter the index can apply. Changes are passed on after a short pause, so typing does
 * not search on every key; chips and switches apply at once.
 */
const props = defineProps<{ query: QueryState }>();
const emit = defineEmits<{ change: [QueryState] }>();
const { t, platformLabel } = useI18n();
const roots = useRoots();

const MAX_SAFE = Number.MAX_SAFE_INTEGER;
const form = reactive({
  text: '',
  useRegex: false,
  fields: [] as Field[],
  roots: [] as string[],
  folder: '',
  platforms: [] as string[],
  models: [] as string[],
  samplers: [] as string[],
  seed: '',
  steps: [null, null] as [number | null, number | null],
  cfg: [null, null] as [number | null, number | null],
  width: '' as string | number,
  height: '' as string | number,
  orientation: 'any' as 'any' | 'portrait' | 'landscape' | 'square',
  dateFrom: '',
  dateTo: '',
  allTags: [] as number[],
  anyTags: [] as number[],
  notTags: [] as number[],
  includeMissing: false,
  sort: 'mtime' as SearchSort,
  direction: 'desc' as 'desc' | 'asc',
});

function load(q: QueryState) {
  form.useRegex = !!q.regex;
  form.text = q.regex ?? q.text ?? '';
  form.fields = (q.text_in ?? []) as Field[];
  form.roots = q.root_ids ?? [];
  form.folder = q.path_prefix ?? '';
  form.platforms = q.platforms ?? [];
  form.models = q.models ?? [];
  form.samplers = q.samplers ?? [];
  form.seed = q.seed === null || q.seed === undefined ? '' : String(q.seed);
  form.steps = (q.steps as [number | null, number | null]) ?? [null, null];
  form.cfg = (q.cfg as [number | null, number | null]) ?? [null, null];
  form.width = q.width ?? '';
  form.height = q.height ?? '';
  form.orientation = q.orientation ?? 'any';
  form.dateFrom = q.date?.[0] ?? '';
  form.dateTo = q.date?.[1] ?? '';
  form.allTags = q.all_tags ?? [];
  form.anyTags = q.any_tags ?? [];
  form.notTags = q.not_tags ?? [];
  form.includeMissing = !!q.include_missing;
  form.sort = q.sort ?? 'mtime';
  form.direction = q.descending === false ? 'asc' : 'desc';
}
load(props.query);

function toQuery(): QueryState {
  const seed = form.seed.trim();
  const seedValue = /^\d+$/.test(seed) ? (Number(seed) > MAX_SAFE ? (seed as unknown as number) : Number(seed)) : null;
  const num = (v: string | number) => (v === '' || v === null ? null : Number(v));
  return {
    text: form.useRegex ? null : form.text.trim() || null,
    regex: form.useRegex ? form.text.trim() || null : null,
    text_in: form.fields.length ? form.fields : null,
    root_ids: form.roots.length ? form.roots : null,
    path_prefix: form.roots.length === 1 && form.folder.trim() ? form.folder.trim() : null,
    platforms: form.platforms.length ? form.platforms : null,
    models: form.models.length ? form.models : null,
    samplers: form.samplers.length ? form.samplers : null,
    seed: seedValue,
    steps: form.steps[0] === null && form.steps[1] === null ? null : form.steps,
    cfg: form.cfg[0] === null && form.cfg[1] === null ? null : form.cfg,
    width: num(form.width),
    height: num(form.height),
    orientation: form.orientation === 'any' ? null : form.orientation,
    date: form.dateFrom || form.dateTo ? [form.dateFrom || null, form.dateTo || null] : null,
    all_tags: form.allTags,
    any_tags: form.anyTags,
    not_tags: form.notTags,
    include_missing: form.includeMissing,
    sort: form.sort,
    descending: form.direction === 'desc',
  };
}

let timer: ReturnType<typeof setTimeout> | undefined;
const loading = ref(false);
watch(
  form,
  () => {
    if (loading.value) return;
    clearTimeout(timer);
    timer = setTimeout(() => emit('change', toQuery()), 350);
  },
  { deep: true },
);
watch(
  () => props.query,
  (q) => {
    loading.value = true;
    load(q);
    // Let the deep watcher see the reload before changes count as the user's again.
    setTimeout(() => (loading.value = false), 0);
  },
);

// Facets narrow as the other filters do, but ignore their own field so a choice can be widened.
const baseForFacets = computed(() => ({ ...props.query, platforms: null, models: null, samplers: null }));
const facets = useFacets(baseForFacets);

const fieldOptions: Field[] = ['prompt', 'negative', 'name', 'model', 'loras'];
const toggleField = (f: Field) => (form.fields = form.fields.includes(f) ? form.fields.filter((x) => x !== f) : [...form.fields, f]);
const toggleRoot = (id: string) => (form.roots = form.roots.includes(id) ? form.roots.filter((x) => x !== id) : [...form.roots, id]);
const sortOptions = computed(() => (['mtime', 'ctime', 'name', 'size', 'seed', 'random'] as SearchSort[]).map((value) => ({ value, label: t(`sort.${value}`) })));

function reset() {
  load({});
  emit('change', {});
}
</script>

<template>
  <form class="search-form" @submit.prevent="emit('change', toQuery())">
    <TextField v-model="form.text" :label="form.useRegex ? t('search.regex') : t('search.text')" :placeholder="t('search.textPlaceholder')" :icon="icons.Search" @enter="emit('change', toQuery())" />
    <div class="chips">
      <Chip v-for="f in fieldOptions" :key="f" :label="t(`search.fields.${f}`)" :selected="form.fields.includes(f)" @click="toggleField(f)" />
      <Chip label=".*" :title="t('search.regex')" :selected="form.useRegex" @click="form.useRegex = !form.useRegex" />
    </div>

    <fieldset v-if="(roots.data.value?.length ?? 0) > 1" class="group">
      <legend class="type-label-large muted">{{ t('search.scope') }}</legend>
      <div class="chips">
        <Chip v-for="r in roots.data.value ?? []" :key="r.id" :label="r.name" :selected="form.roots.includes(r.id)" @click="toggleRoot(r.id)" />
      </div>
    </fieldset>
    <TextField v-if="form.roots.length === 1 || (roots.data.value?.length ?? 0) === 1" v-model="form.folder" :label="t('search.folder')" :icon="icons.Folder" @update:model-value="(roots.data.value?.length ?? 0) === 1 && !form.roots.length && (form.roots = [roots.data.value![0].id])" />

    <FacetList v-model="form.platforms" :label="t('search.platform')" :values="facets.data.value?.platforms ?? []" :format="platformLabel" />
    <FacetList v-model="form.models" :label="t('search.model')" :values="facets.data.value?.models ?? []" />
    <FacetList v-model="form.samplers" :label="t('search.sampler')" :values="facets.data.value?.samplers ?? []" :format="(v) => samplerLabel(v) || v" />

    <TextField v-model="form.seed" :label="t('search.seed')" :icon="icons.Hash" />
    <RangeField v-model="form.steps" :label="t('search.steps')" :min-label="t('common.min')" :max-label="t('common.max')" />
    <RangeField v-model="form.cfg" :label="t('search.cfg')" :min-label="t('common.min')" :max-label="t('common.max')" />
    <div class="pair">
      <TextField v-model="form.width" type="number" :label="t('search.width')" />
      <TextField v-model="form.height" type="number" :label="t('search.height')" />
    </div>
    <div class="group">
      <span class="type-label-large muted">{{ t('search.orientation') }}</span>
      <SegmentedButton
        v-model="form.orientation"
        :options="(['any', 'portrait', 'landscape', 'square'] as const).map((value) => ({ value, label: t(`search.orientations.${value}`) }))"
      />
    </div>
    <fieldset class="group">
      <legend class="type-label-large muted">{{ t('search.dates') }}</legend>
      <div class="pair">
        <label class="date"><span class="type-body-small muted">{{ t('search.dateFrom') }}</span><input v-model="form.dateFrom" type="date" /></label>
        <label class="date"><span class="type-body-small muted">{{ t('search.dateTo') }}</span><input v-model="form.dateTo" type="date" /></label>
      </div>
    </fieldset>
    <TagSelect v-model="form.allTags" :label="t('search.allTags')" />
    <TagSelect v-model="form.anyTags" :label="t('search.anyTags')" />
    <TagSelect v-model="form.notTags" :label="t('search.notTags')" />
    <Switch v-model="form.includeMissing" :label="t('search.includeMissing')" />
    <div class="pair">
      <SelectField :model-value="form.sort" :label="t('sort.label')" :options="sortOptions" @update:model-value="form.sort = ($event as SearchSort) ?? 'mtime'" />
      <SegmentedButton
        v-model="form.direction"
        :options="[
          { value: 'desc', icon: icons.ArrowDownWideNarrow, ariaLabel: t('sort.descending') },
          { value: 'asc', icon: icons.ArrowUpNarrowWide, ariaLabel: t('sort.ascending') },
        ]"
      />
    </div>
    <div class="buttons">
      <AppButton variant="text" @click="reset">{{ t('search.reset') }}</AppButton>
      <AppButton type="submit" :icon="icons.Search">{{ t('search.run') }}</AppButton>
    </div>
  </form>
</template>

<style scoped>
.search-form { display: flex; flex-direction: column; gap: var(--app-space-3); }
.chips { display: flex; flex-wrap: wrap; gap: var(--app-space-1); }
.group { display: flex; flex-direction: column; gap: var(--app-space-2); margin: 0; padding: 0; border: 0; min-width: 0; }
legend { padding: 0 0 var(--app-space-1); }
.pair { display: flex; gap: var(--app-space-2); align-items: center; }
.pair > * { flex: 1; min-width: 0; }
.date { display: flex; flex-direction: column; gap: var(--app-space-1); }
.date input {
  height: 40px; padding: 0 var(--app-space-2); border: 1px solid var(--md-sys-color-outline); border-radius: var(--md-sys-shape-corner-extra-small);
  background: transparent; color: var(--md-sys-color-on-surface); font: inherit; color-scheme: inherit;
}
.buttons { display: flex; justify-content: flex-end; gap: var(--app-space-2); }
</style>
