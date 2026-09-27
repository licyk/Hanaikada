<script setup lang="ts">
import { computed } from 'vue';
import type { ParseResult } from '@/api/types';
import { copyText } from '@/components/imageActions';
import { useI18n } from '@/i18n';
import { AppButton, AppDialog, DataList, ExpansionPanel, useSnackbar } from '@/ui';

/** The metadata of a dropped file, read without storing it: the PNG Info tab. */
const props = defineProps<{ name: string; result: ParseResult | null }>();
const open = defineModel<boolean>('open', { default: false });
const { t, platformLabel } = useI18n();
const snackbar = useSnackbar();
const info = computed(() => props.result?.info);
const rows = computed(() => {
  const i = info.value;
  if (!i) return [];
  return [
    { label: t('info.platform'), value: `${platformLabel(i.platform)}${i.platform_version ? ` ${i.platform_version}` : ''}` },
    { label: t('info.seed'), value: i.seed === null ? null : String(i.seed) },
    { label: t('info.steps'), value: i.steps },
    { label: t('info.cfg'), value: i.cfg_scale },
    { label: t('info.sampler'), value: [i.sampler, i.scheduler].filter(Boolean).join(' · ') },
    { label: t('info.size'), value: i.width ? `${i.width} × ${i.height}` : null },
    { label: t('info.model'), value: i.model?.name },
    { label: t('info.loras'), value: i.loras.map((l) => `${l.name}${l.weight !== null ? ` ${l.weight}` : ''}`).join(', ') },
  ];
});
async function copy(text: string | null | undefined) {
  if (!text) return;
  await copyText(text);
  snackbar.show(t('common.copied'));
}
</script>

<template>
  <AppDialog v-model:open="open" :title="name" width="large" :close-label="t('common.close')">
    <div v-if="result" class="parse">
      <p v-if="result.error" class="error type-body-small">{{ t('info.parseError', { error: result.error }) }}</p>
      <p v-if="info?.platform === 'none'" class="muted type-body-medium">{{ t('info.noMetadata') }}</p>
      <div v-if="info?.prompt" class="block">
        <span class="type-label-large">{{ t('info.prompt') }}</span>
        <p class="prompt type-body-medium" @click="copy(info.prompt)">{{ info.prompt }}</p>
      </div>
      <div v-if="info?.negative_prompt" class="block">
        <span class="type-label-large">{{ t('info.negative') }}</span>
        <p class="prompt type-body-medium" @click="copy(info.negative_prompt)">{{ info.negative_prompt }}</p>
      </div>
      <DataList :rows="rows" />
      <ExpansionPanel v-for="chunk in result.raw.chunks" :key="chunk.key" :label="chunk.key" :supporting-text="chunk.source ?? ''">
        <pre class="raw">{{ chunk.value }}</pre>
      </ExpansionPanel>
    </div>
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.close') }}</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.parse { display: flex; flex-direction: column; gap: var(--app-space-3); }
.block { display: flex; flex-direction: column; gap: var(--app-space-1); }
.prompt { margin: 0; padding: var(--app-space-3); white-space: pre-wrap; overflow-wrap: anywhere; border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container-highest); cursor: copy; }
.raw { margin: 0; max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: var(--md-sys-typescale-body-small-size); }
.error { color: var(--md-sys-color-error); margin: 0; }
</style>
