<script setup lang="ts">
import { computed } from 'vue';
import type { GridEntry } from '@/components/gridKeyboard';
import { useI18n } from '@/i18n';
import type { Selection } from '@/stores/selection';
import { IconButton, Switch, collapseHooks, icons } from '@/ui';

/** What can be done with the selection, shown while something is selected. */
const props = defineProps<{ selection: Selection; entries: GridEntry[]; allKeys: string[] }>();
const emit = defineEmits<{ action: [string] }>();
const { t } = useI18n();
// Favourites, tags and compare are for image files (videos, audio and other files are not indexed).
const images = computed(() => props.entries.filter((e) => e.kind === 'image' && e.item.kind === 'image').length);
const keep = computed({ get: () => props.selection.keep.value, set: (v: boolean) => (props.selection.keep.value = v) });
</script>

<template>
  <!-- The slot grows to the bar's height, so the grid below slides down instead of jumping. -->
  <Transition name="collapse" v-bind="collapseHooks">
    <div v-if="selection.count.value" class="selection-slot">
      <div class="selection-bar" role="toolbar" :aria-label="t('selection.selected', { n: selection.count.value })">
        <IconButton :icon="icons.X" :label="t('selection.clear')" @click="selection.clear()" />
        <span class="type-title-small count">{{ t('selection.selected', { n: selection.count.value }) }}</span>
        <IconButton :icon="icons.SquareCheck" :label="t('selection.selectAll')" @click="selection.selectAll(allKeys)" />
        <span class="spacer" />
        <IconButton v-if="images" :icon="icons.Heart" :label="t('menu.favorite')" @click="emit('action', 'favorite')" />
        <IconButton v-if="images" :icon="icons.Tag" :label="t('selection.tag')" @click="emit('action', 'tags')" />
        <IconButton v-if="images === 2 && entries.length === 2" :icon="icons.Columns2" :label="t('selection.compare')" @click="emit('action', 'compare')" />
        <IconButton :icon="icons.FolderInput" :label="t('selection.moveTo')" @click="emit('action', 'moveTo')" />
        <IconButton :icon="icons.Copy" :label="t('selection.copyTo')" @click="emit('action', 'copyTo')" />
        <IconButton :icon="icons.Download" :label="t('selection.zip')" @click="emit('action', 'zip')" />
        <IconButton :icon="icons.Trash2" :label="t('common.delete')" @click="emit('action', 'delete')" />
        <Switch v-model="keep" class="keep" :label="t('selection.keep')" />
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.selection-slot { flex: none; }
.selection-bar {
  display: flex; align-items: center; gap: var(--app-space-1); flex-wrap: wrap; margin: 0 var(--app-space-4) var(--app-space-2); padding: 0 var(--app-space-2);
  min-height: 56px; border-radius: var(--md-sys-shape-corner-large); background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container);
  --md-icon-button-icon-color: var(--md-sys-color-on-secondary-container);
}
.count { white-space: nowrap; }
.spacer { flex: 1; }
.keep { min-height: 40px; gap: var(--app-space-2); }
</style>
