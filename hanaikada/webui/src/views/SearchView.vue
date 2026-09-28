<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getClientState, putClientState } from '@/api/queries/app';
import { parseFile } from '@/api/queries/images';
import { useSearch } from '@/api/queries/search';
import { useCustomTags } from '@/api/queries/tags';
import { api, unwrap } from '@/api/client';
import { type ImageItem, type ParseResult, type SearchPage, type SearchQuery, itemFromRecord } from '@/api/types';
import FileDropZone, { type DroppedFile } from '@/components/FileDropZone.vue';
import type { GridEntry } from '@/components/gridKeyboard';
import { type ActionId, useImageActions } from '@/components/imageActions';
import ImageGrid from '@/components/ImageGrid.vue';
import ParseDialog from '@/components/ParseDialog.vue';
import SearchForm from '@/components/SearchForm.vue';
import SelectionBar from '@/components/SelectionBar.vue';
import { useI18n } from '@/i18n';
import { type QueryState, decodeQuery, encodeQuery } from '@/search/url';
import { useDialogsStore } from '@/stores/dialogs';
import { usePreferencesStore } from '@/stores/preferences';
import { useSelection } from '@/stores/selection';
import { useViewerStore } from '@/stores/viewer';
import { useWindowClass } from '@/theme/breakpoints';
import { AppMenu, Chip, ContextMenu, EmptyState, IconButton, Skeleton, TRANSITIONS, icons, type MenuItem, useElementHeight, useKeepScroll, useSnackbar } from '@/ui';

const HISTORY_KEY = 'search-history';
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const prefs = usePreferencesStore();
const viewer = useViewerStore();
const actions = useImageActions();
const customTags = useCustomTags();
const selection = useSelection();
const snackbar = useSnackbar();
const dialogs = useDialogsStore();
const windowClass = useWindowClass();
const compact = computed(() => windowClass.value === 'compact' || windowClass.value === 'medium');
const formOpen = ref(!compact.value);

// The search lives in the address. The page is kept alive while another is shown, so it follows
// only its own address: another page's has no ``q`` and must not clear the results.
const str = (v: unknown) => (typeof v === 'string' ? v : '');
const q = ref(str(route.query.q));
watch(
  () => route.query.q,
  (v) => {
    if (route.name === 'search') q.value = str(v);
  },
);
const query = computed<QueryState>(() => decodeQuery(q.value || null));
const search = useSearch(() => ({ ...query.value, limit: 300 }));
const items = computed<ImageItem[]>(() => (search.data.value?.pages ?? []).flatMap((p) => p.items.map(itemFromRecord)));
const total = computed(() => search.data.value?.pages[0]?.total ?? null);
const tagColors = computed(() => new Map((customTags.data.value ?? []).map((tag) => [tag.id, tag.color ?? null])));

function apply(next: QueryState) {
  const encoded = encodeQuery(next);
  if (encoded === q.value) return;
  router.replace({ query: encoded ? { q: encoded } : {} });
  remember(encoded);
}

// -- history: the last 20 searches, kept on the server as client state ------------------------------

const history = ref<string[]>([]);
getClientState<string[]>(HISTORY_KEY)
  .then((v) => (history.value = Array.isArray(v) ? v : []))
  .catch(() => undefined);
let historyTimer: ReturnType<typeof setTimeout> | undefined;
function remember(q: string) {
  if (!q) return;
  clearTimeout(historyTimer);
  historyTimer = setTimeout(() => {
    history.value = [q, ...history.value.filter((x) => x !== q)].slice(0, 20);
    putClientState(HISTORY_KEY, history.value).catch(() => undefined);
  }, 2000);
}
const describe = (q: string) => {
  const s = decodeQuery(q);
  return [s.text ?? s.regex, s.models?.join(', '), s.platforms?.join(', '), s.seed != null ? `seed ${s.seed}` : null, s.sort === 'random' ? t('search.random') : null].filter(Boolean).join(' · ') || t('search.recent');
};
const historyItems = computed<MenuItem[]>(() => history.value.map((q) => ({ id: q, label: describe(q), icon: icons.History })));

// -- tagging every result, not only the pages loaded --------------------------------------------------

const MAX_BULK = 20_000;
const collecting = ref(false);
async function tagAllResults() {
  collecting.value = true;
  try {
    const all: ImageItem[] = [];
    let cursor: string | null = null;
    do {
      const page: SearchPage = await unwrap(api.POST('/api/v1/search', { body: { ...query.value, limit: 1000, cursor } as SearchQuery }));
      all.push(...page.items.map(itemFromRecord));
      cursor = page.next_cursor ?? null;
    } while (cursor && all.length < MAX_BULK);
    if (all.length) dialogs.openTags(all);
  } catch (e) {
    snackbar.error((e as Error).message);
  } finally {
    collecting.value = false;
  }
}

const formPane = ref<HTMLElement | null>(null);
useKeepScroll(formPane);
// On a narrow screen the form covers the results below the toolbar, which stays usable however
// many rows it wraps onto; its button closes the form again.
const toolbar = ref<HTMLElement | null>(null);
const toolbarHeight = useElementHeight(toolbar);

const presets = { random: () => apply({ sort: 'random', random_seed: Math.floor(Math.random() * 2 ** 31) }), recent: () => apply({}) };

// -- grid, viewer and actions -----------------------------------------------------------------------

const hasMore = computed(() => !!search.hasNextPage.value);
function openImage(item: ImageItem) {
  viewer.show({ items: () => items.value, hasMore: () => hasMore.value, loadMore: () => search.fetchNextPage() }, item.key);
}
const entries = computed(() => new Map(items.value.map((i) => [i.key, { kind: 'image' as const, key: i.key, item: i } as GridEntry])));
const selected = computed(() => [...selection.keys.value].map((k) => entries.value.get(k)).filter((e): e is GridEntry => !!e));
const menu = reactive({ open: false, x: 0, y: 0, items: [] as (MenuItem & { divider?: boolean })[] });
function onContext(payload: { entry: GridEntry; x: number; y: number }) {
  const chosen = selection.has(payload.entry.key) ? selected.value : [payload.entry];
  Object.assign(menu, { open: true, x: payload.x, y: payload.y, items: actions.menuFor(chosen) });
}
const runAction = (id: string) => actions.run(id as ActionId, selected.value, { openImage, afterDelete: () => selection.clear() });
watch(query, () => selection.keep.value || selection.clear());

// -- reading a dropped file without storing it ---------------------------------------------------------

const parsed = reactive({ open: false, name: '', result: null as ParseResult | null });
async function parseDropped(files: DroppedFile[]) {
  const file = files[0]?.file;
  if (!file) return;
  try {
    parsed.result = await parseFile(file);
    parsed.name = file.name;
    parsed.open = true;
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}
</script>

<template>
  <div class="search-view" :class="{ compact }">
    <!-- A drawer over the results on a narrow screen; beside them, a pane that pushes them aside. -->
    <Transition :name="compact ? TRANSITIONS.drawer : TRANSITIONS.pane">
      <aside v-if="formOpen" ref="formPane" class="form-pane" :style="compact ? { top: `${toolbarHeight}px` } : undefined">
        <SearchForm :query="query" @change="apply" />
      </aside>
    </Transition>
    <section class="results">
      <div ref="toolbar" class="toolbar">
        <IconButton :icon="icons.ListFilter" :label="t('search.showForm')" :tonal="formOpen" @click="formOpen = !formOpen" />
        <span class="type-title-medium count">
          <template v-if="total !== null">{{ t('search.results', { n: total }) }}</template>
          <template v-else-if="items.length">{{ t('search.resultsMore', { n: items.length }) }}</template>
        </span>
        <Chip :label="t('search.random')" :icon="icons.Dices" @click="presets.random" />
        <Chip :label="t('search.recent')" :icon="icons.Clock" @click="presets.recent" />
        <AppMenu :items="historyItems" @select="(q) => router.replace({ query: { q } })">
          <template #default="{ toggle }"><IconButton :icon="icons.History" :label="t('search.history')" :disabled="!history.length" @click="toggle" /></template>
        </AppMenu>
        <IconButton :icon="icons.Tags" :label="t('tags.applyToResults')" :disabled="!items.length || collecting" :spin="collecting" @click="tagAllResults" />
        <input v-model.number="prefs.prefs.cellSize" class="size" type="range" min="96" max="512" step="8" :aria-label="t('browse.cellSize')" />
      </div>
      <SelectionBar :selection="selection" :entries="selected" :all-keys="items.map((i) => i.key)" @action="runAction" />
      <FileDropZone class="drop" :label="t('search.parseText')" @files="parseDropped">
        <p v-if="search.error.value" class="type-body-medium error">{{ (search.error.value as Error).message }}</p>
        <div v-else-if="search.isLoading.value && !items.length" class="skeletons">
          <Skeleton v-for="i in 12" :key="i" :width="`${prefs.prefs.cellSize}px`" :height="`${prefs.prefs.cellSize}px`" shape="medium" />
        </div>
        <EmptyState v-else-if="!items.length" :icon="icons.Search" :title="t('search.noResults')" :text="t('search.noResultsText')" />
        <ImageGrid
          v-else
          :items="items"
          :selection="selection"
          :cell-size="prefs.prefs.cellSize"
          :show-names="prefs.prefs.showNames"
          :tag-colors="tagColors"
          :favorite-id="actions.favoriteId.value"
          :has-more="hasMore"
          :loading-more="search.isFetchingNextPage.value"
          :label="t('search.title')"
          @open="openImage"
          @preview="openImage"
          @near-end="search.fetchNextPage()"
          @context="onContext"
          @delete="runAction('delete')"
        />
      </FileDropZone>
    </section>
    <ContextMenu v-model:open="menu.open" :items="menu.items" :x="menu.x" :y="menu.y" @select="runAction" />
    <ParseDialog v-model:open="parsed.open" :name="parsed.name" :result="parsed.result" />
  </div>
</template>

<style scoped>
/* Clipped sideways: the form slides in from beyond the start edge. */
.search-view { position: relative; display: flex; height: 100%; min-height: 0; overflow-x: clip; }
.form-pane { width: var(--app-width-pane); flex: none; overflow-y: auto; padding: var(--app-space-4); border-right: 1px solid var(--md-sys-color-outline-variant); }
.compact .form-pane { position: absolute; top: 56px; left: 0; right: 0; bottom: 0; z-index: 5; width: auto; background: var(--md-sys-color-surface-container-low); border: 0; }
.results { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.toolbar { display: flex; align-items: center; gap: var(--app-space-2); min-height: 56px; padding: var(--app-space-1) var(--app-space-2); flex-wrap: wrap; }
.count { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.size { width: 96px; accent-color: var(--md-sys-color-primary); }
.drop { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.drop > :deep(.image-grid) { flex: 1; }
.skeletons { display: flex; flex-wrap: wrap; gap: var(--app-space-2); padding: var(--app-space-4); overflow: hidden; }
.error { color: var(--md-sys-color-error); padding: var(--app-space-4); overflow-wrap: anywhere; }
@media (max-width: 599px) {
  .size { display: none; }
}
</style>
