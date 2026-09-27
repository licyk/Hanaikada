<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useTagMutations, useTags } from '@/api/queries/tags';
import type { Tag, TagType } from '@/api/types';
import { useI18n } from '@/i18n';
import { encodeQuery } from '@/search/url';
import { AppButton, AppDialog, ConfirmDialog, EmptyState, IconButton, SearchField, Skeleton, Tabs, TextField, TRANSITIONS, icons, useSnackbar } from '@/ui';

/** Every tag by type with its count. Custom tags can be created, renamed, recoloured and deleted. */
const { t } = useI18n();
const router = useRouter();
const snackbar = useSnackbar();
const mutations = useTagMutations();
const TYPES: TagType[] = ['custom', 'board', 'prompt', 'lora', 'model', 'sampler', 'platform', 'size'];
const type = ref<TagType>('custom');
const filter = ref('');
const tags = useTags(type, filter, 2000);
const tabs = computed(() => TYPES.map((value) => ({ value, label: t(`tags.types.${value}`) })));
// The list slides the way the tabs moved: forward to a tab on the right, back to one on the left.
const axisDir = ref(1);
watch(type, (next, prev) => (axisDir.value = TYPES.indexOf(next) >= TYPES.indexOf(prev) ? 1 : -1));
const max = computed(() => Math.max(1, ...(tags.data.value ?? []).map((tag) => tag.count)));

const editing = ref<Tag | null>(null);
const creating = ref(false);
const form = ref({ name: '', color: '' });
const deleting = ref<Tag | null>(null);
const dialogOpen = computed({ get: () => creating.value || !!editing.value, set: (v) => !v && ((creating.value = false), (editing.value = null)) });
const deleteOpen = computed({ get: () => !!deleting.value, set: (v) => !v && (deleting.value = null) });

function startCreate() {
  form.value = { name: '', color: '' };
  creating.value = true;
}
function startEdit(tag: Tag) {
  form.value = { name: tag.name, color: tag.color ?? '' };
  editing.value = tag;
}
async function save() {
  const name = form.value.name.trim();
  if (!name) return;
  try {
    if (editing.value) await mutations.update.mutateAsync({ id: editing.value.id, body: { name, color: form.value.color || null } });
    else await mutations.create.mutateAsync({ name, color: form.value.color || null });
    dialogOpen.value = false;
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}
async function remove() {
  if (!deleting.value) return;
  try {
    await mutations.remove.mutateAsync(deleting.value.id);
    deleting.value = null;
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}
const show = (tag: Tag) => router.push({ name: 'search', query: { q: encodeQuery({ all_tags: [tag.id] }) } });
</script>

<template>
  <div class="tags-view" :style="{ '--axis-dir': axisDir }">
    <!-- One header on the card's rounded top edge: the tabs and the filter stay in view together. -->
    <header class="head">
      <div class="tabs"><Tabs v-model="type" :tabs="tabs" /></div>
      <div class="toolbar">
        <SearchField v-model="filter" class="filter" :placeholder="t('tags.filter')" />
        <AppButton v-if="type === 'custom'" :icon="icons.Plus" @click="startCreate">{{ t('tags.create') }}</AppButton>
      </div>
    </header>
    <Transition :name="TRANSITIONS.sharedAxisX">
      <div :key="type" class="panel">
        <div v-if="tags.isLoading.value" class="list"><Skeleton v-for="i in 8" :key="i" height="48px" /></div>
        <EmptyState v-else-if="!tags.data.value?.length" :icon="icons.Tags" :title="t('tags.empty')" />
        <ul v-else class="list">
          <li v-for="tag in tags.data.value" :key="tag.id" class="row">
            <button type="button" class="main state-layer" @click="show(tag)">
              <span v-if="tag.type === 'custom'" class="swatch" :style="{ background: tag.color ?? undefined }" />
              <span class="type-body-large name">{{ tag.name === 'favorite' && tag.type === 'custom' ? `♥ ${t('tags.favorite')}` : tag.name }}</span>
              <span class="bar"><span class="fill" :style="{ width: `${(tag.count / max) * 100}%` }" /></span>
              <span class="type-label-large count">{{ tag.count }}</span>
            </button>
            <template v-if="tag.type === 'custom'">
              <IconButton :icon="icons.Pencil" :label="t('common.edit')" @click="startEdit(tag)" />
              <IconButton :icon="icons.Trash2" :label="t('common.delete')" :disabled="tag.name === 'favorite'" @click="deleting = tag" />
            </template>
          </li>
        </ul>
      </div>
    </Transition>

    <AppDialog v-model:open="dialogOpen" :title="editing ? t('common.edit') : t('tags.create')" width="small" :close-label="t('common.close')">
      <div class="form">
        <TextField v-model="form.name" :label="t('tags.name')" @enter="save" />
        <label class="color-row">
          <span class="type-body-large">{{ t('tags.color') }}</span>
          <input v-model="form.color" type="color" class="color" :aria-label="t('tags.color')" />
        </label>
      </div>
      <template #actions>
        <AppButton variant="text" @click="dialogOpen = false">{{ t('common.cancel') }}</AppButton>
        <AppButton :disabled="!form.name.trim()" @click="save">{{ t('common.save') }}</AppButton>
      </template>
    </AppDialog>
    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('tags.deleteTitle', { name: deleting?.name ?? '' })"
      :message="t('tags.deleteText')"
      :confirm-label="t('common.delete')"
      :cancel-label="t('common.cancel')"
      danger
      @confirm="remove"
    />
  </div>
</template>

<style scoped>
.tags-view { position: relative; overflow-x: clip; display: flex; flex-direction: column; gap: var(--app-space-3); padding-bottom: var(--app-space-6); min-height: 100%; }
/* One tab's content; the leaving one slides out over the entering one (shared-axis-x). */
.panel { flex: 1; display: flex; flex-direction: column; }
.head {
  position: sticky; top: 0; z-index: 1; display: flex; flex-direction: column;
  /* The shell's content card is the panel: the header takes its colour and its top corners. */
  background: var(--md-sys-color-surface-container-low); border-radius: var(--md-sys-shape-corner-large) var(--md-sys-shape-corner-large) 0 0;
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
}
.tabs {
  overflow-x: auto; padding: 0 var(--app-space-2); border-radius: inherit;
  --md-primary-tab-container-color: transparent; --md-divider-color: transparent;
}
.tabs :deep(md-primary-tab) { border-radius: var(--md-sys-shape-corner-medium) var(--md-sys-shape-corner-medium) 0 0; }
.toolbar { display: flex; gap: var(--app-space-3); align-items: center; flex-wrap: wrap; padding: var(--app-space-2) var(--app-space-4) var(--app-space-3); }
.filter { flex: 1; min-width: 200px; }
.list { list-style: none; margin: 0; padding: 0 var(--app-space-4); display: flex; flex-direction: column; gap: var(--app-space-1); }
.row { display: flex; align-items: center; gap: var(--app-space-1); }
.main {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: var(--app-space-3); height: 48px; padding: 0 var(--app-space-3);
  border: 0; border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); color: var(--md-sys-color-on-surface); cursor: pointer; font: inherit; text-align: left;
}
.swatch { width: 14px; height: 14px; border-radius: 50%; flex: none; background: var(--md-sys-color-tertiary); }
.name { flex: 0 1 auto; min-width: 0; max-width: 50%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { flex: 1; height: 6px; border-radius: var(--md-sys-shape-corner-full); background: var(--md-sys-color-surface-container-highest); overflow: hidden; }
.fill { display: block; height: 100%; background: var(--md-sys-color-primary); }
.count { min-width: 48px; text-align: right; }
.form { display: flex; flex-direction: column; gap: var(--app-space-3); }
.color-row { display: flex; align-items: center; justify-content: space-between; }
.color { width: 56px; height: 40px; padding: 0; border: 1px solid var(--md-sys-color-outline); border-radius: var(--md-sys-shape-corner-small); background: transparent; cursor: pointer; }
</style>
