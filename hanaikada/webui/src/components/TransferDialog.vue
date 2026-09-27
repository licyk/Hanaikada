<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useLibraryMutations, useRoots } from '@/api/queries/library';
import FolderTree from '@/components/FolderTree.vue';
import { useI18n } from '@/i18n';
import { useDialogsStore } from '@/stores/dialogs';
import { AppButton, AppDialog, SegmentedButton, SelectField, Switch, useSnackbar } from '@/ui';

/** Move or copy files and folders: pick a destination (or confirm a dropped one), and what to do on a clash. */
const dialogs = useDialogsStore();
const { t } = useI18n();
const roots = useRoots();
const library = useLibraryMutations();
const snackbar = useSnackbar();

const open = computed({ get: () => !!dialogs.transfer, set: (v) => !v && (dialogs.transfer = null) });
const rootId = ref<string | null>(null);
const dir = ref('');
const copy = ref(false);
const onConflict = ref<'error' | 'rename' | 'skip'>('rename');
const keepGoing = ref(true);
const preset = computed(() => dialogs.transfer?.dir !== null && dialogs.transfer?.dir !== undefined);
const count = computed(() => dialogs.transfer?.refs.length ?? 0);

watch(
  () => dialogs.transfer,
  (state) => {
    if (!state) return;
    rootId.value = state.rootId ?? state.refs[0]?.root_id ?? roots.data.value?.[0]?.id ?? null;
    dir.value = state.dir ?? '';
    copy.value = state.copy;
  },
);

const rootOptions = computed(() => (roots.data.value ?? []).map((r) => ({ value: r.id, label: r.name })));
const rootName = computed(() => roots.data.value?.find((r) => r.id === rootId.value)?.name ?? '');
const busy = computed(() => library.move.isPending.value || library.copy.isPending.value);

async function run(asCopy: boolean) {
  const state = dialogs.transfer;
  if (!state || !rootId.value) return;
  const body = { items: state.refs, dest_root_id: rootId.value, dest_dir: dir.value, on_conflict: onConflict.value, continue_on_error: keepGoing.value };
  try {
    const result = await (asCopy ? library.copy : library.move).mutateAsync(body);
    const done = result.paths.length;
    if (result.errors.length) snackbar.error(t('transfer.failed', { n: result.errors.length, first: result.errors[0].message }));
    else snackbar.show(t(asCopy ? 'transfer.copied' : 'transfer.moved', { n: done }));
    dialogs.transfer = null;
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}
</script>

<template>
  <AppDialog v-model:open="open" :title="t(copy ? 'transfer.copyTitle' : 'transfer.moveTitle', { n: count })" width="small">
    <div class="form">
      <p v-if="preset" class="type-body-medium">{{ t('transfer.chooseAction', { n: count, dest: `${rootName}/${dir}` }) }}</p>
      <template v-else>
        <SelectField v-model="rootId" :label="t('transfer.destination')" :options="rootOptions" @update:model-value="dir = ''" />
        <div class="tree" role="tree">
          <FolderTree v-if="rootId" :key="rootId" :root-id="rootId" path="" :name="rootName" :selected="dir" @select="dir = $event" />
        </div>
        <p class="type-body-small muted path">{{ rootName }}/{{ dir }}</p>
      </template>
      <div class="row">
        <span class="type-body-medium">{{ t('transfer.onConflict') }}</span>
        <SegmentedButton
          v-model="onConflict"
          :options="[
            { value: 'rename', label: t('transfer.conflictRename') },
            { value: 'skip', label: t('transfer.conflictSkip') },
            { value: 'error', label: t('transfer.conflictError') },
          ]"
        />
      </div>
      <Switch v-model="keepGoing" :label="t('transfer.continueOnError')" />
    </div>
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.cancel') }}</AppButton>
      <template v-if="preset">
        <AppButton variant="tonal" :loading="busy" @click="run(true)">{{ t('transfer.dropCopy') }}</AppButton>
        <AppButton :loading="busy" @click="run(false)">{{ t('transfer.dropMove') }}</AppButton>
      </template>
      <AppButton v-else :loading="busy" :disabled="!rootId" @click="run(copy)">{{ copy ? t('common.copy') : t('common.move') }}</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: var(--app-space-3); }
.tree { max-height: clamp(300px, 45vh, 640px); overflow: auto; padding: var(--app-space-1); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); }
.row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--app-space-2); }
.path { margin: 0; overflow-wrap: anywhere; }
p { margin: 0; }
</style>
