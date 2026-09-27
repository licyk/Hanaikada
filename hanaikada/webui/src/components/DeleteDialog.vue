<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useMeta, useSettings } from '@/api/queries/app';
import { useLibraryMutations } from '@/api/queries/library';
import { useI18n } from '@/i18n';
import { useDialogsStore } from '@/stores/dialogs';
import { Checkbox, ConfirmDialog, useSnackbar } from '@/ui';

/** Confirm a delete: to the trash by default, or permanently. */
const dialogs = useDialogsStore();
const { t } = useI18n();
const settings = useSettings();
const meta = useMeta();
const library = useLibraryMutations();
const snackbar = useSnackbar();
const open = computed({ get: () => !!dialogs.remove, set: (v) => !v && (dialogs.remove = null) });
const permanent = ref(false);
const toTrash = computed(() => settings.data.value?.library.delete_to_trash !== false);
const count = computed(() => dialogs.remove?.refs.length ?? 0);

watch(
  () => dialogs.remove,
  (v) => v && (permanent.value = !toTrash.value),
);

async function confirm() {
  const state = dialogs.remove;
  if (!state) return;
  try {
    await library.remove.mutateAsync({ items: state.refs, permanent: permanent.value });
    snackbar.show(t('delete.deleted', { n: state.refs.length }));
    state.onDone?.();
    dialogs.remove = null;
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}
</script>

<template>
  <ConfirmDialog
    v-model:open="open"
    :title="t('delete.title', { n: count })"
    :message="permanent ? t('delete.permanentText') : t('delete.toTrash', { where: meta.data.value?.trash_location ?? '' })"
    :confirm-label="t('common.delete')"
    :cancel-label="t('common.cancel')"
    :loading="library.remove.isPending.value"
    danger
    @confirm="confirm"
  >
    <Checkbox v-if="toTrash" v-model="permanent" :label="t('delete.permanent')" />
  </ConfirmDialog>
</template>
