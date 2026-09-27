<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { detectLayout, useLibraryMutations } from '@/api/queries/library';
import type { RootInfo } from '@/api/types';
import { useI18n } from '@/i18n';
import { AppButton, AppDialog, PathField, SegmentedButton, Switch, TextField } from '@/ui';

type Layout = 'auto' | 'sd-webui' | 'comfyui' | 'invokeai' | 'custom';

/** Add or edit a root: a folder, its layout (detected when adding), and whether it is indexed. */
const props = defineProps<{ root?: RootInfo | null }>();
const open = defineModel<boolean>('open', { default: false });
const { t } = useI18n();
const mutations = useLibraryMutations();
const form = reactive({ name: '', path: '', layout: 'auto' as Layout, enabled: true, index: true });
const error = ref<string | null>(null);
const detected = ref<string | null>(null);

watch(open, (v) => {
  if (!v) return;
  form.name = props.root?.name ?? '';
  form.path = props.root?.path ?? '';
  form.layout = props.root?.layout ?? 'auto';
  form.enabled = props.root?.enabled ?? true;
  form.index = props.root?.index ?? true;
  error.value = null;
  detected.value = null;
});

let detectTimer: ReturnType<typeof setTimeout> | undefined;
watch(
  () => form.path,
  (path) => {
    clearTimeout(detectTimer);
    detected.value = null;
    if (props.root || !path.trim().startsWith('/') && !/^[A-Za-z]:/.test(path.trim())) return;
    detectTimer = setTimeout(async () => {
      try {
        const s = await detectLayout(path.trim());
        detected.value = t('roots.detected', { layout: t(`layouts.${s.layout}`), reason: s.reason });
      } catch {
        detected.value = null;
      }
    }, 400);
  },
);

const layouts = computed(() =>
  (props.root ? (['sd-webui', 'comfyui', 'invokeai', 'custom'] as Layout[]) : (['auto', 'sd-webui', 'comfyui', 'invokeai', 'custom'] as Layout[])).map((value) => ({ value, label: t(`layouts.${value}`) })),
);
const busy = computed(() => mutations.addRoot.isPending.value || mutations.updateRoot.isPending.value);

async function submit() {
  if (!form.path.trim()) return;
  error.value = null;
  try {
    if (props.root) {
      const layout = form.layout === 'auto' ? undefined : form.layout;
      await mutations.updateRoot.mutateAsync({ id: props.root.id, body: { name: form.name.trim() || null, path: form.path.trim(), layout, enabled: form.enabled, index: form.index } });
    } else {
      await mutations.addRoot.mutateAsync({ name: form.name.trim() || null, path: form.path.trim(), layout: form.layout, enabled: form.enabled, index: form.index });
    }
    open.value = false;
  } catch (e) {
    error.value = (e as Error).message;
  }
}
</script>

<template>
  <AppDialog v-model:open="open" :title="root ? t('roots.edit') : t('roots.add')" width="small" :close-label="t('common.close')">
    <div class="form">
      <PathField v-model="form.path" :label="t('roots.path')" placeholder="/path/to/stable-diffusion-webui" :supporting-text="detected ?? t('roots.pathHelp')" :error-text="error ?? undefined" @enter="submit" />
      <TextField v-model="form.name" :label="t('roots.name')" />
      <div class="layout">
        <span class="type-label-large muted">{{ t('roots.layout') }}</span>
        <SegmentedButton v-model="form.layout" :options="layouts" />
      </div>
      <Switch v-model="form.index" :label="t('roots.index')" :supporting-text="t('roots.indexHelp')" />
      <Switch v-if="root" v-model="form.enabled" :label="t('roots.enabled')" />
    </div>
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.cancel') }}</AppButton>
      <AppButton :loading="busy" :disabled="!form.path.trim()" @click="submit">{{ t('common.save') }}</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--app-space-3); }
.layout { display: flex; flex-direction: column; gap: var(--app-space-2); overflow-x: auto; }
</style>
