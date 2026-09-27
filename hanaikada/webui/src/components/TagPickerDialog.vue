<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useCustomTags, useTagMutations } from '@/api/queries/tags';
import type { Tag } from '@/api/types';
import { useI18n } from '@/i18n';
import { useDialogsStore } from '@/stores/dialogs';
import { AppButton, AppDialog, Chip, TextField, icons, useSnackbar } from '@/ui';

/**
 * Custom tags for one or more images. A tag every image has is selected; clicking it removes it
 * from all, clicking any other adds it to all. A new tag is created and applied in one step.
 */
const dialogs = useDialogsStore();
const { t } = useI18n();
const tags = useCustomTags();
const mutations = useTagMutations();
const snackbar = useSnackbar();
const open = computed({ get: () => !!dialogs.tags, set: (v) => !v && (dialogs.tags = null) });
const filter = ref('');
const newName = ref('');
/** Changes made in this dialog, so the chips answer at once instead of waiting for a refetch. */
const local = ref(new Map<number, boolean>());
watch(
  () => dialogs.tags,
  (v) => {
    if (v) {
      filter.value = '';
      newName.value = '';
      local.value = new Map();
    }
  },
);

const items = computed(() => dialogs.tags?.items ?? []);
// Indexed images go by id; one not indexed yet goes by path, and the server indexes it first.
const body = computed(() => ({
  image_ids: items.value.filter((i) => i.image).map((i) => i.image!.id),
  paths: items.value.filter((i) => !i.image).map((i) => [i.rootId, i.path] as [string, string]),
}));
function state(tag: Tag): 'all' | 'some' | 'none' {
  if (local.value.has(tag.id)) return local.value.get(tag.id) ? 'all' : 'none';
  const n = items.value.filter((i) => (i.image?.tag_ids ?? []).includes(tag.id)).length;
  return n === 0 ? 'none' : n === items.value.length ? 'all' : 'some';
}
const shown = computed(() => (tags.data.value ?? []).filter((tag) => !filter.value || tag.name.toLowerCase().includes(filter.value.toLowerCase())));

async function toggle(tag: Tag) {
  const add = state(tag) !== 'all';
  try {
    const result = await mutations.apply.mutateAsync({ id: tag.id, add, body: body.value });
    local.value = new Map(local.value).set(tag.id, add);
    snackbar.show(t(add ? 'tags.applied' : 'tags.removed', { n: result.changed, tag: tag.name }));
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}

async function create() {
  const name = newName.value.trim();
  if (!name) return;
  try {
    const tag = await mutations.create.mutateAsync({ name, color: null });
    newName.value = '';
    await toggle(tag);
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}
</script>

<template>
  <AppDialog v-model:open="open" :title="`${t('tags.picker')} · ${t('common.images', { n: items.length })}`" width="small">
    <div class="picker">
      <TextField v-if="(tags.data.value?.length ?? 0) > 12" v-model="filter" :label="t('tags.filter')" :icon="icons.Search" />
      <div class="chips">
        <Chip
          v-for="tag in shown"
          :key="tag.id"
          :label="tag.name === 'favorite' ? t('tags.favorite') : tag.name"
          :icon="tag.name === 'favorite' ? icons.Heart : state(tag) === 'some' ? icons.Minus : undefined"
          :selected="state(tag) === 'all'"
          :dot="tag.color"
          @click="toggle(tag)"
        />
      </div>
      <div class="new">
        <TextField v-model="newName" :label="t('tags.newName')" @enter="create" />
        <AppButton variant="tonal" :icon="icons.Plus" :disabled="!newName.trim()" @click="create">{{ t('common.add') }}</AppButton>
      </div>
    </div>
    <template #actions>
      <AppButton variant="text" @click="open = false">{{ t('common.close') }}</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.picker { display: flex; flex-direction: column; gap: var(--app-space-3); }
.chips { display: flex; flex-wrap: wrap; gap: var(--app-space-2); }
.new { display: flex; align-items: flex-start; gap: var(--app-space-2); }
.new > :first-child { flex: 1; min-width: 0; }
</style>
