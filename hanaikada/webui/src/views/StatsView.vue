<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useStats } from '@/api/queries/search';
import type { FacetValue } from '@/api/types';
import { formatCount } from '@/format';
import { useI18n } from '@/i18n';
import { samplerLabel } from '@/metadata/samplers';
import { encodeQuery, type QueryState } from '@/search/url';
import { BarChart, EmptyState, Heatmap, Skeleton, Surface, icons } from '@/ui';

/** How many images were made when, and with what: a year's heatmap, monthly bars and top lists. */
const { t, tl, platformLabel } = useI18n();
const router = useRouter();
const stats = useStats(null);
const s = computed(() => stats.data.value);
const months = computed(() => (s.value?.per_month ?? []).slice(-24).map((m) => ({ label: m.day.slice(2).replace('-', '/'), value: m.count })));
const top = (values: FacetValue[] | undefined) => {
  const list = values ?? [];
  const max = Math.max(1, ...list.map((v) => v.count));
  return list.map((v) => ({ ...v, share: (v.count / max) * 100 }));
};
const lists = computed(() => [
  { title: t('stats.topModels'), rows: top(s.value?.models), query: (v: string): QueryState => ({ models: [v] }), label: (v: string) => v },
  { title: t('stats.topSamplers'), rows: top(s.value?.samplers), query: (v: string): QueryState => ({ samplers: [v] }), label: (v: string) => samplerLabel(v) || v },
  { title: t('stats.topLoras'), rows: top(s.value?.loras), query: (v: string): QueryState => ({ text: v, text_in: ['loras'] }), label: (v: string) => v },
  { title: t('stats.platforms'), rows: top(s.value?.platforms), query: (v: string): QueryState => ({ platforms: [v] }), label: platformLabel },
]);
const go = (q: QueryState) => router.push({ name: 'search', query: { q: encodeQuery(q) } });
</script>

<template>
  <div class="stats">
    <div v-if="stats.isLoading.value" class="grid"><Skeleton v-for="i in 4" :key="i" height="200px" shape="medium" /></div>
    <EmptyState v-else-if="!s || !s.total" :icon="icons.BarChart3" :title="t('stats.empty')" />
    <template v-else>
      <Surface :level="0" shape="large" class="card wide">
        <div class="total"><span class="type-display-small">{{ formatCount(s.total) }}</span><span class="muted type-body-large">{{ t('stats.total') }}</span></div>
        <h2 class="type-title-medium">{{ t('stats.perDay') }}</h2>
        <div class="scroll"><Heatmap :days="s.per_day" :label="t('stats.perDay')" :day-names="tl('stats.days')" /></div>
      </Surface>
      <Surface :level="0" shape="large" class="card wide">
        <h2 class="type-title-medium">{{ t('stats.perMonth') }}</h2>
        <BarChart :bars="months" :label="t('stats.perMonth')" />
      </Surface>
      <div class="grid">
        <Surface v-for="list in lists" :key="list.title" :level="0" shape="large" class="card">
          <h2 class="type-title-medium">{{ list.title }}</h2>
          <button v-for="row in list.rows" :key="row.value" type="button" class="row state-layer" @click="go(list.query(row.value))">
            <span class="type-body-medium label">{{ list.label(row.value) }}</span>
            <span class="bar"><span class="fill" :style="{ width: `${row.share}%` }" /></span>
            <span class="type-label-large count">{{ row.count }}</span>
          </button>
        </Surface>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stats { display: flex; flex-direction: column; gap: var(--app-space-4); padding: var(--app-space-4) var(--app-space-6) var(--app-space-8); min-height: 100%; box-sizing: border-box; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: var(--app-space-4); }
.card { display: flex; flex-direction: column; gap: var(--app-space-2); padding: var(--app-space-4) var(--app-space-5); min-width: 0; }
.total { display: flex; align-items: baseline; gap: var(--app-space-3); }
h2 { margin: var(--app-space-2) 0 0; }
.scroll { overflow-x: auto; }
.row { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) auto; align-items: center; gap: var(--app-space-3); padding: var(--app-space-1) var(--app-space-2); border: 0; border-radius: var(--md-sys-shape-corner-small); background: transparent; color: var(--md-sys-color-on-surface); cursor: pointer; font: inherit; text-align: left; }
.label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { height: 6px; border-radius: var(--md-sys-shape-corner-full); background: var(--md-sys-color-surface-container-highest); overflow: hidden; }
.fill { display: block; height: 100%; background: var(--md-sys-color-primary); }
.count { min-width: 40px; text-align: right; }
@media (max-width: 599px) {
  .stats { padding: var(--app-space-3); }
}
</style>
