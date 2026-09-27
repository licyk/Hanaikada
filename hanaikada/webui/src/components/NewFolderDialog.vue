<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useLibraryMutations } from '@/api/queries/library';
import { useI18n } from '@/i18n';
import { useDialogsStore } from '@/stores/dialogs';
import { AppButton, AppDialog, TextField } from '@/ui';

const dialogs = useDialogsStore();
const { t } = useI18n();
const library = useLibraryMutations();
const open = computed({ get: () => !!dialogs.newFolder, set: (v) => !v && (dialogs.newFolder = null) });
const name = ref('');
const error = ref<string | null>(null);
watch(
  () => dialogs.newFolder,
  (v) => {
    if (v) {
      name.value = '';
      error.value = null;
    }
  },
);

async function submit() {
  const state = dialogs.newFolder;
  if (!state || !name.value.trim()) return;
  try {
    await library.createFolder.mutateAsync({ root_id: state.rootId, path: state.dir, name: name.value.trim() });
    dialogs.newFolder = null;
  } catch (e) {
    error.value = (e as Error).message;
  }
}
</script>

<template>
  <AppDialog v-model:open="open" :title="t('browse.newFolder')" width="small">
    <TextField v-model="name" :label="t('browse.folderName')" :error-text="error ?? undefined" @enter="submit" />
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.cancel') }}</AppButton>
      <AppButton :loading="library.createFolder.isPending.value" :disabled="!name.trim()" @click="submit">{{ t('common.create') }}</AppButton>
    </template>
  </AppDialog>
</template>
