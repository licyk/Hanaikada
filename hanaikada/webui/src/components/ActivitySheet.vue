<script setup lang="ts">
import { computed } from 'vue';
import { useRoots } from '@/api/queries/library';
import { useIndexMutations, useIndexRoots } from '@/api/queries/index';
import { formatBytes, formatDate } from '@/format';
import { useI18n } from '@/i18n';
import { useScanStore } from '@/stores/scan';
import { useUploadsStore } from '@/stores/uploads';
import { AppButton, Badge, Divider, IconButton, ProgressBar, SideSheet, icons, useSnackbar } from '@/ui';

/** What the server is doing: each root's scan, with scan, rebuild and stop, and the uploads in flight. */
const scan = useScanStore();
const uploads = useUploadsStore();
const roots = useRoots();
const summary = useIndexRoots();
const mutations = useIndexMutations();
const snackbar = useSnackbar();
const { t, locale } = useI18n();

const rows = computed(() =>
  (roots.data.value ?? []).map((root) => ({
    root,
    state: scan.roots[root.id],
    summary: summary.data.value?.find((s) => s.root_id === root.id) ?? null,
  })),
);

function start(rootId: string | null, full = false, reparse = false) {
  mutations.scan.mutate({ root_id: rootId, path: null, full, reparse }, { onError: (e) => snackbar.error((e as Error).message) });
}
</script>

<template>
  <SideSheet v-model:open="scan.sheetOpen" :title="t('scan.title')" :close-label="t('common.close')">
    <div class="sheet">
      <div class="actions">
        <AppButton variant="tonal" :icon="icons.RefreshCw" @click="start(null)">{{ t('scan.scanAll') }}</AppButton>
        <AppButton v-if="scan.running || scan.queued" variant="text" :icon="icons.Ban" @click="mutations.cancel.mutate()">{{ t('scan.cancel') }}</AppButton>
      </div>
      <p v-if="!rows.length" class="muted type-body-medium">{{ t('scan.nothing') }}</p>
      <section v-for="row in rows" :key="row.root.id" class="root">
        <div class="head">
          <span class="type-title-small name">{{ row.root.name }}</span>
          <Badge v-if="row.state?.state === 'scanning'" tone="primary" :value="t('scan.scanning')" />
          <Badge v-else-if="row.state?.state === 'queued'" tone="neutral" :value="t('scan.queued')" />
          <Badge v-else-if="row.state?.state === 'failed'" tone="error" :value="t('scan.failed')" />
          <IconButton :icon="icons.RefreshCw" :label="t('scan.scan')" :disabled="!row.root.index" @click="start(row.root.id)" />
          <IconButton :icon="icons.RotateCcw" :label="`${t('scan.rebuild')}: ${t('scan.rebuildHelp')}`" :disabled="!row.root.index" @click="start(row.root.id, true)" />
        </div>
        <template v-if="row.state?.state === 'scanning'">
          <ProgressBar />
          <p class="type-body-small">{{ t('scan.progress', { indexed: row.state.files_indexed, seen: row.state.files_seen, failed: row.state.files_failed }) }} · {{ t('scan.folders', { n: row.state.folders_seen }) }}</p>
          <p v-if="row.state.current" class="type-body-small muted current">{{ row.state.current }}</p>
        </template>
        <p v-if="row.state?.error" class="type-body-small error">{{ row.state.error }}</p>
        <p v-if="row.summary" class="type-body-small muted">
          {{ t('scan.images', { n: row.summary.images }) }}
          <template v-if="row.summary.missing"> · {{ t('scan.missing', { n: row.summary.missing }) }}</template>
          <template v-if="row.summary.failed"> · {{ t('scan.parseFailures', { n: row.summary.failed }) }}</template>
          <template v-if="row.state?.finished_at"> · {{ t('scan.lastScan', { when: formatDate(row.state.finished_at, locale) }) }}</template>
        </p>
      </section>
      <AppButton variant="text" :icon="icons.FileSearch" @click="start(null, false, true)">{{ t('scan.reparse') }}</AppButton>
      <p class="type-body-small muted">{{ t('scan.reparseHelp') }}</p>

      <template v-if="uploads.items.length">
        <Divider />
        <div class="head">
          <span class="type-title-small name">{{ t('scan.uploads') }}</span>
          <AppButton variant="text" @click="uploads.clearFinished()">{{ t('scan.clearFinished') }}</AppButton>
        </div>
        <div v-for="u in uploads.items" :key="u.id" class="upload">
          <div class="head">
            <span class="type-body-medium name">{{ u.name }}</span>
            <span class="type-body-small muted">{{ formatBytes(u.loaded) }} / {{ formatBytes(u.size) }}</span>
            <IconButton v-if="u.state === 'queued' || u.state === 'uploading'" :icon="icons.X" :label="t('common.cancel')" @click="uploads.cancel(u.id)" />
          </div>
          <ProgressBar v-if="u.state === 'uploading'" :value="u.size ? u.loaded / u.size : null" />
          <p v-if="u.error" class="type-body-small error">{{ u.error }}</p>
        </div>
      </template>
    </div>
  </SideSheet>
</template>

<style scoped>
.sheet { display: flex; flex-direction: column; gap: var(--app-space-3); }
.actions { display: flex; flex-wrap: wrap; gap: var(--app-space-2); }
.root, .upload { display: flex; flex-direction: column; gap: var(--app-space-1); padding: var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); }
.head { display: flex; align-items: center; gap: var(--app-space-2); }
.name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.current { overflow-wrap: anywhere; }
.error { color: var(--md-sys-color-error); overflow-wrap: anywhere; }
p { margin: 0; }
</style>
