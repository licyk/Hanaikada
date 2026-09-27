<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useTree } from '@/api/queries/library';
import type { PathRef } from '@/api/types';
import { DRAG_TYPE } from '@/components/gridKeyboard';
import { AppIcon, collapseHooks, icons } from '@/ui';

defineOptions({ name: 'FolderTree' });

/**
 * One node of the folder tree. Children load when the node opens (depth 1 per request), and nodes
 * on the path to the selected folder open by themselves. A node accepts dragged grid cells.
 */
/** ``selected`` is null where nothing in this tree is the current folder (All folders); ``open`` sets how the node starts. */
const props = withDefaults(defineProps<{ rootId: string; path: string; name: string; label?: string | null; hasChildren?: boolean; selected: string | null; depth?: number; open?: boolean }>(), {
  depth: 0,
  label: null,
  hasChildren: true,
  open: undefined,
});
const emit = defineEmits<{ select: [string]; transfer: [{ refs: PathRef[]; rootId: string; dir: string; copy: boolean }] }>();
const isAncestor = (p: string) => props.selected !== null && (p === '' || props.selected === p || props.selected.startsWith(`${p}/`));
const expanded = ref(props.open ?? (props.depth === 0 || (isAncestor(props.path) && props.selected !== props.path)));
const node = useTree(() => props.rootId, () => props.path, expanded);
const children = computed(() => node.data.value?.children ?? []);
const dropping = ref(false);

watch(
  () => props.selected,
  () => {
    if (isAncestor(props.path) && props.selected !== props.path) expanded.value = true;
  },
);

function onDragOver(event: DragEvent) {
  if (!event.dataTransfer || !Array.from(event.dataTransfer.types).includes(DRAG_TYPE)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = event.ctrlKey || event.altKey ? 'copy' : 'move';
  dropping.value = true;
}

function onDrop(event: DragEvent) {
  dropping.value = false;
  const data = event.dataTransfer?.getData(DRAG_TYPE);
  if (!data) return;
  event.preventDefault();
  const refs = (JSON.parse(data) as PathRef[]).filter((r) => !(r.root_id === props.rootId && (r.path === props.path || props.path.startsWith(`${r.path}/`))));
  if (refs.length) emit('transfer', { refs, rootId: props.rootId, dir: props.path, copy: event.ctrlKey || event.altKey });
}
</script>

<template>
  <div class="tree-node" role="treeitem" :aria-expanded="hasChildren ? expanded : undefined" :aria-selected="selected === path">
    <div
      class="row state-layer"
      :class="{ active: selected === path, dropping }"
      :style="{ paddingInlineStart: `${depth * 12 + 4}px` }"
      @click="emit('select', path)"
      @dragover="onDragOver"
      @dragleave="dropping = false"
      @drop="onDrop"
    >
      <button v-if="hasChildren" type="button" class="toggle" :aria-label="expanded ? 'Collapse' : 'Expand'" @click.stop="expanded = !expanded">
        <AppIcon :icon="icons.ChevronRight" :size="18" class="chevron" :class="{ open: expanded }" />
      </button>
      <span v-else class="toggle" />
      <AppIcon :icon="selected === path ? icons.FolderOpen : icons.Folder" :size="18" />
      <span class="type-label-large name" :title="name">{{ name }}</span>
      <span v-if="label" class="label type-label-small">{{ label }}</span>
    </div>
    <Transition name="collapse" v-bind="collapseHooks">
      <div v-if="expanded && children.length" role="group">
        <FolderTree
          v-for="child in children"
          :key="child.path"
          :root-id="rootId"
          :path="child.path"
          :name="child.name"
          :label="child.label"
          :has-children="child.has_children"
          :selected="selected"
          :depth="depth + 1"
          @select="emit('select', $event)"
          @transfer="emit('transfer', $event)"
        />
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.row {
  display: flex; align-items: center; gap: var(--app-space-1); height: 36px; padding-right: var(--app-space-2);
  border-radius: var(--md-sys-shape-corner-full); cursor: pointer; color: var(--md-sys-color-on-surface-variant);
}
.row.active { background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); }
.row.dropping { outline: 2px solid var(--md-sys-color-primary); outline-offset: -2px; }
.toggle { display: grid; place-items: center; width: 24px; height: 24px; flex: none; border: 0; padding: 0; background: transparent; color: inherit; cursor: pointer; border-radius: 50%; }
.chevron { transition: transform var(--md-sys-motion-duration-short4) var(--md-sys-motion-easing-standard); }
.chevron.open { transform: rotate(90deg); }
.name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.label { margin-left: auto; padding: 0 var(--app-space-2); border-radius: var(--md-sys-shape-corner-full); background: var(--md-sys-color-tertiary-container); color: var(--md-sys-color-on-tertiary-container); }
</style>
