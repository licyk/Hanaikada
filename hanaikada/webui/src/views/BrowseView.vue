<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ApiError } from '@/api/client';
import { useSettings } from '@/api/queries/app';
import { COMBINED_VIEW_ID } from '@/api/queries/keys';
import { useCombinedEntries, useEntries, useRoots } from '@/api/queries/library';
import { useFacets, useSearch } from '@/api/queries/search';
import { useCustomTags } from '@/api/queries/tags';
import { type FacetValue, type ImageItem, type ListSort, itemFromEntry, itemFromRecord } from '@/api/types';
import FileDropZone, { type DroppedFile } from '@/components/FileDropZone.vue';
import FolderTree from '@/components/FolderTree.vue';
import type { GridEntry, GridFolder } from '@/components/gridKeyboard';
import { type ActionId, useImageActions } from '@/components/imageActions';
import ImageGrid from '@/components/ImageGrid.vue';
import RootDialog from '@/components/RootDialog.vue';
import SelectionBar from '@/components/SelectionBar.vue';
import { parentPath, pathSegments } from '@/format';
import { useI18n } from '@/i18n';
import { samplerLabel } from '@/metadata/samplers';
import { useDialogsStore } from '@/stores/dialogs';
import { usePreferencesStore } from '@/stores/preferences';
import { useSelection } from '@/stores/selection';
import { useUploadsStore } from '@/stores/uploads';
import { useViewerStore } from '@/stores/viewer';
import { useWindowClass } from '@/theme/breakpoints';
import { AppButton, AppMenu, Breadcrumbs, Chip, ContextMenu, EmptyState, IconButton, SelectField, Skeleton, icons, type MenuItem, TRANSITIONS, useElementHeight, useKeepScroll, useSnackbar } from '@/ui';

const { t, platformLabel } = useI18n();
const route = useRoute();
const router = useRouter();
const prefs = usePreferencesStore();
const viewer = useViewerStore();
const dialogs = useDialogsStore();
const uploads = useUploadsStore();
const snackbar = useSnackbar();
const actions = useImageActions();
const roots = useRoots();
const settings = useSettings();
const customTags = useCustomTags();
const selection = useSelection();
const windowClass = useWindowClass();
const wide = computed(() => windowClass.value !== 'compact' && windowClass.value !== 'medium');

const str = (v: unknown) => (typeof v === 'string' ? v : null);
const rootId = ref<string | null>(str(route.query.root) ?? prefs.prefs.lastRoot);
const path = ref(str(route.query.path) ?? '');
const flat = ref(route.query.flat === '1');
const seed = ref(Math.floor(Math.random() * 2 ** 31));
const filters = reactive({ platform: null as string | null, model: null as string | null, sampler: null as string | null });
const rootDialogOpen = ref(false);
const treeOpen = ref(false);

// "All folders" (library.combined_view) is the root id "*": every root's output folders side by side.
// When it is offered it comes first, and Browse opens on it unless a root was chosen before.
const settingsKnown = computed(() => !!settings.data.value || settings.isError.value);
const combinedOffered = computed(() => settings.data.value?.library.combined_view === true && !!roots.data.value?.length);
const isCombined = computed(() => rootId.value === COMBINED_VIEW_ID);

// Checked on either side changing: a folder removed while the page was hidden can come back in the
// address the navigation remembered.
watch(
  [() => roots.data.value, rootId, combinedOffered, settingsKnown],
  ([list]) => {
    if (!list) return;
    // Until the settings say whether "All folders" is offered, neither keep nor replace it.
    if (!settingsKnown.value && (rootId.value === null || isCombined.value)) return;
    const valid = isCombined.value ? combinedOffered.value : list.some((r) => r.id === rootId.value);
    if (!valid) {
      rootId.value = combinedOffered.value ? COMBINED_VIEW_ID : (list.find((r) => r.enabled)?.id ?? list[0]?.id ?? null);
      path.value = '';
    }
  },
  { immediate: true },
);
// There is no single folder below "All folders" to flatten.
watch(isCombined, (on) => on && (flat.value = false));
// The page is kept alive while another is shown: only its own address speaks for it, and it writes
// its address only while shown, catching up when it is shown again.
const shown = () => route.name === 'browse';
function writeUrl() {
  if (!shown()) return;
  router.replace({ query: { root: rootId.value ?? undefined, path: path.value || undefined, flat: flat.value ? '1' : undefined } });
}
onActivated(writeUrl);
watch([rootId, path, flat], ([r]) => {
  if (r) prefs.prefs.lastRoot = r;
  writeUrl();
  if (!selection.keep.value) selection.clear();
  filters.platform = filters.model = filters.sampler = null;
  grid.value?.scrollToTop();
});
watch(
  () => [route.query.root, route.query.path, route.query.flat],
  ([r, p, f]) => {
    if (!shown()) return;
    const nextRoot = str(r) ?? rootId.value;
    if (nextRoot !== rootId.value) rootId.value = nextRoot;
    if ((str(p) ?? '') !== path.value) path.value = str(p) ?? '';
    flat.value = f === '1';
  },
);

const root = computed(() => roots.data.value?.find((r) => r.id === rootId.value) ?? null);
const combined = useCombinedEntries(isCombined);
const listingOptions = computed(() => ({ sort: prefs.prefs.sort, desc: prefs.prefs.desc, seed: prefs.prefs.sort === 'random' ? seed.value : undefined }));
const entries = useEntries(() => (isCombined.value ? null : rootId.value), path, listingOptions, () => !flat.value);

// Flatten mode: the grid becomes a search for everything below this folder.
const searchQuery = computed(() => ({
  root_ids: rootId.value ? [rootId.value] : [],
  path_prefix: path.value,
  sort: prefs.prefs.sort,
  descending: prefs.prefs.desc,
  random_seed: prefs.prefs.sort === 'random' ? seed.value : null,
  platforms: filters.platform ? [filters.platform] : null,
  models: filters.model ? [filters.model] : null,
  samplers: filters.sampler ? [filters.sampler] : null,
  limit: 300,
}));
const flatOn = () => flat.value && !!rootId.value && !isCombined.value;
const search = useSearch(searchQuery, flatOn);
const facets = useFacets(() => ({ ...searchQuery.value, platforms: null, models: null, samplers: null }), flatOn);

const pages = computed(() => entries.data.value?.pages ?? []);
const folders = computed<GridFolder[]>(() => (isCombined.value ? (combined.data.value?.folders ?? []) : flat.value ? [] : (pages.value[0]?.folders ?? [])));
const allItems = computed<ImageItem[]>(() => {
  if (isCombined.value) return [];
  if (flat.value) return (search.data.value?.pages ?? []).flatMap((p) => p.items.map(itemFromRecord));
  const id = rootId.value ?? '';
  return pages.value.flatMap((p) => p.files.map((f) => itemFromEntry(id, f)));
});
const items = computed(() => {
  if (flat.value) return allItems.value;
  return allItems.value.filter(
    (i) => (!filters.platform || i.image?.platform === filters.platform) && (!filters.model || i.image?.model_name === filters.model) && (!filters.sampler || i.image?.sampler_norm === filters.sampler),
  );
});
const total = computed(() => (isCombined.value ? null : flat.value ? (search.data.value?.pages[0]?.total ?? null) : (pages.value[0]?.total_files ?? null)));
const hasMore = computed(() => !isCombined.value && (flat.value ? !!search.hasNextPage.value : !!entries.hasNextPage.value));
const loadingMore = computed(() => !isCombined.value && (flat.value ? search.isFetchingNextPage.value : entries.isFetchingNextPage.value));
const loading = computed(() => (isCombined.value ? combined.isLoading.value : flat.value ? search.isLoading.value : entries.isLoading.value));
const error = computed(() => (isCombined.value ? combined.error.value : flat.value ? search.error.value : entries.error.value) as Error | null);
// "12 images" unless the folder also holds videos, audio or other files: then "12 items".
const onlyImages = computed(() => items.value.every((i) => i.kind === 'image'));
const loadMore = () => (isCombined.value ? Promise.resolve() : flat.value ? search.fetchNextPage() : entries.fetchNextPage());
const refresh = () => (isCombined.value ? combined.refetch() : flat.value ? search.refetch() : entries.refetch());
const missingRoots = computed(() => (combined.data.value?.missing_roots ?? []).map((id) => roots.data.value?.find((r) => r.id === id)?.name ?? id));

// A remembered or pasted path that is not in this root (any more) goes back to the root's top.
watch(error, (e) => {
  if (e instanceof ApiError && e.status === 404 && path.value && root.value?.exists) {
    snackbar.error(e.message);
    path.value = '';
  }
});

/** Facet chips: the server's in flatten mode, counted from the loaded files otherwise. */
function countBy(get: (i: ImageItem) => string | null | undefined): FacetValue[] {
  const counts = new Map<string, number>();
  for (const i of allItems.value) {
    const v = get(i);
    if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  return [...counts.entries()].map(([value, count]) => ({ value, count })).sort((a, b) => b.count - a.count);
}
const facetRows = computed(() => {
  if (flat.value) {
    const f = facets.data.value;
    return { platforms: f?.platforms ?? [], models: (f?.models ?? []).slice(0, 8), samplers: (f?.samplers ?? []).slice(0, 6) };
  }
  return { platforms: countBy((i) => i.image?.platform), models: countBy((i) => i.image?.model_name).slice(0, 8), samplers: countBy((i) => i.image?.sampler_norm).slice(0, 6) };
});
const showFacets = computed(() => facetRows.value.platforms.length > 1 || facetRows.value.models.length > 1 || filters.platform || filters.model || filters.sampler);

const tagColors = computed(() => new Map((customTags.data.value ?? []).map((tag) => [tag.id, tag.color ?? null])));
// A leading "All folders" crumb leads back to it from inside a root; its value cannot be a path.
const ALL_CRUMB = '\u0000all';
const crumbs = computed(() => {
  if (isCombined.value) return [{ label: t('browse.allFolders'), value: '' }];
  const trail = [{ label: root.value?.name ?? '', value: '' }, ...pathSegments(path.value).map((s) => ({ label: s.name, value: s.path }))];
  return combinedOffered.value ? [{ label: t('browse.allFolders'), value: ALL_CRUMB }, ...trail] : trail;
});
const rootOptions = computed(() => [
  ...(combinedOffered.value ? [{ value: COMBINED_VIEW_ID, label: t('browse.allFolders') }] : []),
  ...(roots.data.value ?? []).map((r) => ({ value: r.id, label: r.name })),
]);

/** Open a folder: of the current root, or of ``inRoot`` (a folder of "All folders"). */
function navigate(to: string, inRoot?: string) {
  if (to === ALL_CRUMB) {
    rootId.value = COMBINED_VIEW_ID;
    to = '';
  } else if (inRoot && inRoot !== rootId.value) {
    rootId.value = inRoot;
  }
  path.value = to;
  treeOpen.value = false;
}
// Up from a root's top leads to "All folders" when it is offered.
const canGoUp = computed(() => !!path.value || (combinedOffered.value && !isCombined.value));
const goUp = () => (path.value ? navigate(parentPath(path.value)) : canGoUp.value && navigate(ALL_CRUMB));

const grid = ref<InstanceType<typeof ImageGrid> | null>(null);
const side = ref<HTMLElement | null>(null);
useKeepScroll(side);

// Narrower than a desktop, the folder panel is a drawer over the grid. It opens below the toolbar,
// which stays usable (its button closes the drawer again, however many rows the toolbar wraps
// onto); a tap on the grid beside it or Escape closes it too.
const toolbar = ref<HTMLElement | null>(null);
const toolbarHeight = useElementHeight(toolbar);
const drawerOpen = computed(() => !wide.value && treeOpen.value);
const belowToolbar = computed(() => ({ top: `${toolbarHeight.value}px` }));
const onDrawerKey = (event: KeyboardEvent) => event.key === 'Escape' && !event.defaultPrevented && (treeOpen.value = false);
watch(drawerOpen, (open) => (open ? document.addEventListener('keydown', onDrawerKey) : document.removeEventListener('keydown', onDrawerKey)));
onActivated(() => drawerOpen.value && document.addEventListener('keydown', onDrawerKey));
onDeactivated(() => document.removeEventListener('keydown', onDrawerKey));
onBeforeUnmount(() => document.removeEventListener('keydown', onDrawerKey));
function openImage(item: ImageItem) {
  viewer.show({ items: () => items.value, hasMore: () => hasMore.value, loadMore }, item.key);
}

// -- sort menu ------------------------------------------------------------------------------------

const sortItems = computed<MenuItem[]>(() => [
  ...(['mtime', 'ctime', 'name', 'size', 'random'] as ListSort[]).map((s) => ({ id: s, label: t(`sort.${s}`), icon: prefs.prefs.sort === s ? icons.Check : undefined })),
  { id: 'toggle-dir', label: prefs.prefs.desc ? t('sort.ascending') : t('sort.descending'), icon: prefs.prefs.desc ? icons.ArrowUpNarrowWide : icons.ArrowDownWideNarrow },
]);
function onSort(id: string) {
  if (id === 'toggle-dir') prefs.prefs.desc = !prefs.prefs.desc;
  else {
    if (id === 'random') seed.value = Math.floor(Math.random() * 2 ** 31);
    prefs.prefs.sort = id as ListSort;
  }
}

// -- selection, context menu and actions ---------------------------------------------------------

const entryByKey = computed(() => {
  const map = new Map<string, GridEntry>();
  for (const folder of folders.value) {
    const inRoot = folder.root_id ?? rootId.value ?? '';
    const key = `d:${inRoot}:${folder.path}`;
    map.set(key, { kind: 'folder', key, rootId: inRoot, folder });
  }
  for (const item of items.value) map.set(item.key, { kind: 'image', key: item.key, item });
  return map;
});
const selectedEntries = computed(() => [...selection.keys.value].map((k) => entryByKey.value.get(k)).filter((e): e is GridEntry => !!e));
const menu = reactive({ open: false, x: 0, y: 0, items: [] as (MenuItem & { divider?: boolean })[] });

function onContext(payload: { entry: GridEntry; x: number; y: number }) {
  const chosen = selection.has(payload.entry.key) ? selectedEntries.value : [payload.entry];
  Object.assign(menu, { open: true, x: payload.x, y: payload.y, items: actions.menuFor(chosen) });
}
function runAction(id: string, chosen = selectedEntries.value) {
  actions.run(id as ActionId, chosen, { openImage, openFolder: navigate, afterDelete: () => selection.clear() });
}

// -- uploads ------------------------------------------------------------------------------------------

function upload(files: DroppedFile[]) {
  if (!rootId.value || isCombined.value) return;
  uploads.enqueue(rootId.value, path.value, files);
  snackbar.show(t('uploads.uploading', { n: files.length }));
}
function pickFiles() {
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  // Every file type when the library shows them all; media otherwise, as the server accepts.
  if (!settings.data.value?.library.show_all_files) input.accept = 'image/*,video/*,audio/*';
  input.onchange = () => upload(Array.from(input.files ?? []).map((file) => ({ file, relativePath: file.name })));
  input.click();
}
const stopUploads = uploads.onFinished((item) => {
  if (item.state === 'failed') snackbar.error(t('uploads.failed', { name: item.name, error: item.error ?? '' }));
});
onBeforeUnmount(() => stopUploads());
</script>

<template>
  <div class="browse">
    <EmptyState v-if="roots.data.value && !roots.data.value.length" :icon="icons.Blossom" :title="t('browse.noRoots')" :text="t('browse.noRootsText')">
      <AppButton :icon="icons.FolderPlus" @click="rootDialogOpen = true">{{ t('browse.addRoot') }}</AppButton>
    </EmptyState>

    <template v-else>
      <Transition name="scrim">
        <div v-if="drawerOpen" class="scrim" :style="belowToolbar" @click="treeOpen = false" />
      </Transition>
      <!-- As a drawer it slides in from the edge; beside the grid on a wide screen it is simply there. -->
      <Transition :name="TRANSITIONS.drawer" :css="!wide">
        <aside v-if="wide || treeOpen" ref="side" class="side" :class="{ overlay: !wide }" :style="wide ? undefined : belowToolbar">
          <SelectField :model-value="rootId" :label="t('browse.root')" :options="rootOptions" @update:model-value="(v) => { rootId = v; path = ''; }" />
          <template v-if="isCombined">
            <p class="type-body-small muted hint">{{ t('browse.allFoldersHint') }}</p>
            <div class="tree" role="tree" :aria-label="t('browse.allFolders')">
              <FolderTree
                v-for="f in combined.data.value?.folders ?? []"
                :key="`${f.root_id}:${f.path}`"
                :root-id="f.root_id"
                :path="f.path"
                :name="f.display_name"
                :label="f.label"
                :selected="null"
                :open="false"
                @select="(p) => navigate(p, f.root_id)"
                @transfer="(e) => dialogs.openTransfer(e.refs, e.copy, e.rootId, e.dir)"
              />
            </div>
          </template>
          <div v-else-if="rootId && root" class="tree" role="tree" :aria-label="t('browse.tree')">
            <FolderTree :key="rootId" :root-id="rootId" path="" :name="root.name" :selected="path" @select="navigate" @transfer="(e) => dialogs.openTransfer(e.refs, e.copy, e.rootId, e.dir)" />
          </div>
        </aside>
      </Transition>

      <section class="content">
        <div ref="toolbar" class="toolbar">
          <IconButton v-if="!wide" :icon="treeOpen ? icons.FolderOpen : icons.Folder" :label="t('browse.tree')" :tonal="treeOpen" @click="treeOpen = !treeOpen" />
          <IconButton :icon="icons.ArrowUp" :label="t('browse.up')" :disabled="!canGoUp" @click="goUp" />
          <Breadcrumbs class="crumbs" :crumbs="crumbs" @navigate="navigate" />
          <span v-if="total !== null" class="type-label-medium muted count">{{ items.length < (total ?? 0) ? t('browse.shownOf', { shown: items.length, total: total ?? 0 }) : t(onlyImages ? 'common.images' : 'common.items', { n: total ?? 0 }) }}</span>
          <IconButton v-if="!isCombined" :icon="icons.Layers" :label="flat ? t('browse.flattenOff') : t('browse.flatten')" :tonal="flat" @click="flat = !flat" />
          <AppMenu v-if="!isCombined" :items="sortItems" @select="onSort">
            <template #default="{ toggle }"><IconButton :icon="prefs.prefs.desc ? icons.ArrowDownWideNarrow : icons.ArrowUpNarrowWide" :label="t('sort.label')" @click="toggle" /></template>
          </AppMenu>
          <label class="size" :title="t('browse.cellSize')">
            <input v-model.number="prefs.prefs.cellSize" type="range" min="96" max="512" step="8" :aria-label="t('browse.cellSize')" />
          </label>
          <IconButton :icon="prefs.prefs.showNames ? icons.Eye : icons.EyeOff" :label="t('browse.showNames')" @click="prefs.prefs.showNames = !prefs.prefs.showNames" />
          <!-- "All folders" has no single folder to put anything in. -->
          <template v-if="!isCombined">
            <IconButton :icon="icons.FolderPlus" :label="t('browse.newFolder')" :disabled="!rootId" @click="rootId && dialogs.openNewFolder(rootId, path)" />
            <IconButton :icon="icons.Upload" :label="t('common.upload')" :disabled="!rootId" @click="pickFiles" />
          </template>
          <IconButton :icon="icons.RefreshCw" :label="t('common.refresh')" :spin="loading" @click="refresh" />
        </div>

        <div v-if="showFacets" class="facets" role="toolbar" :aria-label="t('browse.filters')">
          <Chip v-for="f in facetRows.platforms" :key="`p${f.value}`" :label="platformLabel(f.value)" :count="f.count" :selected="filters.platform === f.value" @click="filters.platform = filters.platform === f.value ? null : f.value" />
          <span class="sep" />
          <Chip v-for="f in facetRows.models" :key="`m${f.value}`" :label="f.value" :count="f.count" :selected="filters.model === f.value" @click="filters.model = filters.model === f.value ? null : f.value" />
          <span class="sep" />
          <Chip v-for="f in facetRows.samplers" :key="`s${f.value}`" :label="samplerLabel(f.value) || f.value" :count="f.count" :selected="filters.sampler === f.value" @click="filters.sampler = filters.sampler === f.value ? null : f.value" />
        </div>

        <SelectionBar :selection="selection" :entries="selectedEntries" :all-keys="[...entryByKey.keys()]" @action="runAction" />

        <p v-if="isCombined && missingRoots.length" class="type-body-small muted note">{{ t('browse.missingRoots', { names: missingRoots.join(', ') }) }}</p>

        <FileDropZone class="drop" :label="t('browse.dropToUpload')" :disabled="!rootId || isCombined" @files="upload">
          <p v-if="root && !root.exists" class="type-body-medium error">{{ t('browse.missing') }}: {{ root.path }}</p>
          <p v-else-if="error" class="type-body-medium error">{{ error.message }}</p>
          <div v-else-if="loading && !items.length && !folders.length" class="skeletons">
            <Skeleton v-for="i in 12" :key="i" :width="`${prefs.prefs.cellSize}px`" :height="`${prefs.prefs.cellSize}px`" shape="medium" />
          </div>
          <EmptyState v-else-if="!items.length && !folders.length" :icon="icons.Image" :title="t('browse.empty')" :text="isCombined ? t('browse.allFoldersEmpty') : t('browse.emptyText')" />
          <ImageGrid
            v-else
            ref="grid"
            :items="items"
            :folders="folders"
            :root-id="rootId"
            :selection="selection"
            :cell-size="prefs.prefs.cellSize"
            :show-names="prefs.prefs.showNames"
            :tag-colors="tagColors"
            :favorite-id="actions.favoriteId.value"
            :has-more="hasMore"
            :loading-more="loadingMore"
            :label="crumbs.map((c) => c.label).join('/')"
            @open="openImage"
            @preview="openImage"
            @open-folder="navigate"
            @up="goUp"
            @near-end="loadMore"
            @context="onContext"
            @delete="runAction('delete')"
            @transfer="(e) => dialogs.openTransfer(e.refs, e.copy, e.rootId, e.dir)"
          />
        </FileDropZone>
      </section>
    </template>
    <ContextMenu v-model:open="menu.open" :items="menu.items" :x="menu.x" :y="menu.y" @select="runAction($event)" />
    <RootDialog v-model:open="rootDialogOpen" />
  </div>
</template>

<style scoped>
.browse { position: relative; display: flex; height: 100%; min-height: 0; }
.side { display: flex; flex-direction: column; gap: var(--app-space-3); width: var(--app-width-pane); flex: none; padding: var(--app-space-3); border-right: 1px solid var(--md-sys-color-outline-variant); min-height: 0; }
/* The drawer and its scrim start below the toolbar (``top`` is its measured height). */
.side.overlay { position: absolute; left: 0; bottom: 0; z-index: 5; width: min(var(--app-width-pane), 90%); background: var(--md-sys-color-surface-container-low); box-shadow: var(--app-elevation-2); border-top-right-radius: var(--md-sys-shape-corner-large); }
.scrim { position: absolute; left: 0; right: 0; bottom: 0; z-index: 4; background: color-mix(in srgb, var(--md-sys-color-scrim) 32%, transparent); }
.tree { flex: 1; min-height: 0; overflow: auto; }
.hint { margin: 0; padding: 0 var(--app-space-2); }
.note { margin: 0; padding: 0 var(--app-space-4) var(--app-space-2); }
.content { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.toolbar { display: flex; align-items: center; gap: var(--app-space-1); min-height: 56px; padding: var(--app-space-1) var(--app-space-2); flex-wrap: wrap; }
.crumbs { flex: 1; min-width: 0; }
.count { white-space: nowrap; }
.size input { width: 96px; accent-color: var(--md-sys-color-primary); }
.facets { display: flex; gap: var(--app-space-2); padding: 0 var(--app-space-4) var(--app-space-2); overflow-x: auto; scrollbar-width: thin; }
.facets .sep { flex: none; width: 1px; background: var(--md-sys-color-outline-variant); }
.facets .sep:last-child, .facets .sep:first-child { display: none; }
.drop { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.drop > :deep(.image-grid) { flex: 1; }
.skeletons { display: flex; flex-wrap: wrap; gap: var(--app-space-2); padding: var(--app-space-4); overflow: hidden; }
.error { color: var(--md-sys-color-error); padding: var(--app-space-4); overflow-wrap: anywhere; }
@media (max-width: 599px) {
  .size { display: none; }
  /* On a phone the path gets a row of its own above the buttons. */
  .crumbs { flex-basis: 100%; order: -1; }
  .count { display: none; }
}
</style>
