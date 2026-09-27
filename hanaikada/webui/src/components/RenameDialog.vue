<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useLibraryMutations } from '@/api/queries/library';
import { useI18n } from '@/i18n';
import { useDialogsStore } from '@/stores/dialogs';
import { AppButton, AppDialog, TextField, useSnackbar } from '@/ui';

/** Rename an image (its sidecars follow the new stem) or a folder. */
const dialogs = useDialogsStore();
const { t } = useI18n();
const library = useLibraryMutations();
const snackbar = useSnackbar();
const open = computed({ get: () => !!dialogs.rename, set: (v) => !v && (dialogs.rename = null) });
const value = ref('');
const error = ref<string | null>(null);

watch(
  () => dialogs.rename,
  (state) => {
    if (!state) return;
    error.value = null;
    // An image keeps its extension: only the stem is edited.
    value.value = state.isFile ? state.name.replace(/\.[^./]+$/, '') : state.name;
  },
);

async function submit() {
  const state = dialogs.rename;
  const name = value.value.trim();
  if (!state || !name) return;
  try {
    await library.rename.mutateAsync({ root_id: state.ref.root_id, path: state.ref.path, new_name: name });
    dialogs.rename = null;
    snackbar.show(t('common.saved'));
  } catch (e) {
    error.value = (e as Error).message;
  }
}
</script>

<template>
  <AppDialog v-model:open="open" :title="t('rename.title')" width="small">
    <TextField v-model="value" :label="t('rename.newName')" :supporting-text="dialogs.rename?.isFile ? t('rename.help') : dialogs.rename?.name" :error-text="error ?? undefined" @enter="submit" />
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.cancel') }}</AppButton>
      <AppButton :loading="library.rename.isPending.value" :disabled="!value.trim()" @click="submit">{{ t('common.rename') }}</AppButton>
    </template>
  </AppDialog>
</template>
