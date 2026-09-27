<script setup lang="ts">
import { computed, onBeforeUnmount, onDeactivated, ref } from 'vue';
import { useMeta, useSettings, useUpdateSettings, useVersion } from '@/api/queries/app';
import { useIndexMutations, useIndexRoots } from '@/api/queries/index';
import { useLibraryMutations, useRoots, useThumbnailCache } from '@/api/queries/library';
import type { RootInfo } from '@/api/types';
import RootDialog from '@/components/RootDialog.vue';
import { formatBytes } from '@/format';
import { useI18n } from '@/i18n';
import { DEFAULT_SHORTCUTS, type ShortcutAction, usePreferencesStore } from '@/stores/preferences';
import { AppButton, AppIcon, Badge, ConfirmDialog, IconButton, KeyHint, SegmentedButton, SelectField, Skeleton, Slider, Surface, Switch, TextField, TokenField, icons, useSnackbar } from '@/ui';

const { t, localeOptions } = useI18n();
const settings = useSettings();
const update = useUpdateSettings();
const snackbar = useSnackbar();
const prefs = usePreferencesStore();
const roots = useRoots();
const summary = useIndexRoots();
const meta = useMeta();
const version = useVersion();
const cache = useThumbnailCache();
const library = useLibraryMutations();
const index = useIndexMutations();

const s = computed(() => settings.data.value);
const locked = computed(() => !!meta.data.value?.roots_locked);

/** Save one field; each change saves on its own with a snackbar confirmation. */
function save(patch: Record<string, unknown>, restart = false) {
  update.mutate(patch, {
    onSuccess: () => snackbar.show(restart ? `${t('common.saved')} · ${t('settings.restartNeeded')}` : t('common.saved')),
    onError: (e) => snackbar.error((e as Error).message),
  });
}
const num = (v: string | number | null) => (v === '' || v === null ? null : Number(v));
const list = (v: string, sep = /[\s,]+/) => v.split(sep).map((x) => x.trim()).filter(Boolean);
const envNote = (key: string) => (s.value?.env_overrides.includes(key) ? t('settings.envOverrides') : undefined);

// -- roots ----------------------------------------------------------------------------------------

const rootDialog = ref(false);
const editing = ref<RootInfo | null>(null);
const removing = ref<RootInfo | null>(null);
const removeOpen = computed({ get: () => !!removing.value, set: (v) => !v && (removing.value = null) });
const count = (id: string) => summary.data.value?.find((x) => x.root_id === id);
function addRoot() {
  editing.value = null;
  rootDialog.value = true;
}
function editRoot(root: RootInfo) {
  editing.value = root;
  rootDialog.value = true;
}
function patchRoot(root: RootInfo, body: { enabled?: boolean; index?: boolean }) {
  library.updateRoot.mutate({ id: root.id, body }, { onError: (e) => snackbar.error((e as Error).message) });
}
async function removeRoot() {
  if (!removing.value) return;
  try {
    await library.removeRoot.mutateAsync(removing.value.id);
    removing.value = null;
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}
const scanRoot = (id: string, full = false) => index.scan.mutate({ root_id: id, path: null, full, reparse: false }, { onError: (e) => snackbar.error((e as Error).message) });

// -- shortcuts ---------------------------------------------------------------------------------------

const capturing = ref<ShortcutAction | null>(null);
const onCapture = (e: KeyboardEvent) => {
  if (!capturing.value) return;
  e.preventDefault();
  e.stopPropagation();
  if (e.key !== 'Escape') prefs.prefs.shortcuts[capturing.value] = e.key;
  capturing.value = null;
  window.removeEventListener('keydown', onCapture, true);
};
function capture(action: ShortcutAction) {
  capturing.value = action;
  window.addEventListener('keydown', onCapture, true);
}
function stopCapture() {
  capturing.value = null;
  window.removeEventListener('keydown', onCapture, true);
}
// Leaving the page (kept alive) or closing it ends a capture that was waiting for a key.
onDeactivated(stopCapture);
onBeforeUnmount(stopCapture);
const shortcutActions = Object.keys(DEFAULT_SHORTCUTS) as ShortcutAction[];

async function clearCache() {
  try {
    await library.clearThumbnails.mutateAsync();
    snackbar.show(t('settings.cacheCleared'));
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}
</script>

<template>
  <div class="settings">
    <div v-if="!s" class="skeletons"><Skeleton v-for="i in 4" :key="i" height="160px" shape="medium" /></div>
    <template v-else>
      <Surface :level="0" shape="large" class="section">
        <div class="section-head">
          <h2 class="type-title-large">{{ t('settings.sections.roots') }}</h2>
          <AppButton v-if="!locked" variant="tonal" :icon="icons.FolderPlus" @click="addRoot">{{ t('roots.add') }}</AppButton>
        </div>
        <p v-if="locked" class="type-body-small muted">{{ t('roots.locked') }}</p>
        <div v-for="r in roots.data.value ?? []" :key="r.id" class="root">
          <div class="root-head">
            <AppIcon :icon="icons.HardDrive" :size="20" />
            <div class="root-text">
              <span class="type-title-small">{{ r.name }} <span class="muted">· {{ t(`layouts.${r.layout}`) }}</span></span>
              <span class="type-body-small muted path">{{ r.path }}</span>
              <span class="type-body-small muted">
                {{ t('roots.outputs') }}: {{ r.outputs.map((o) => o || '/').join(', ') || '—' }}
                <template v-if="count(r.id)"> · {{ t('scan.images', { n: count(r.id)!.images }) }}</template>
              </span>
            </div>
            <Badge v-if="!r.exists" tone="error" :value="t('roots.missing')" />
            <Badge v-else-if="!r.index" tone="neutral" :value="t('browse.browseOnly')" />
            <IconButton :icon="icons.RefreshCw" :label="t('scan.scan')" :disabled="!r.index || !r.enabled" @click="scanRoot(r.id)" />
            <IconButton :icon="icons.RotateCcw" :label="`${t('scan.rebuild')}: ${t('scan.rebuildHelp')}`" :disabled="!r.index || !r.enabled" @click="scanRoot(r.id, true)" />
            <template v-if="!locked">
              <IconButton :icon="icons.Pencil" :label="t('common.edit')" @click="editRoot(r)" />
              <IconButton :icon="icons.Trash2" :label="t('roots.remove')" @click="removing = r" />
            </template>
          </div>
          <div v-if="!locked" class="root-switches">
            <Switch :model-value="r.enabled" :label="t('roots.enabled')" @update:model-value="patchRoot(r, { enabled: $event })" />
            <Switch :model-value="r.index" :label="t('roots.index')" @update:model-value="patchRoot(r, { index: $event })" />
          </div>
        </div>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.index') }}</h2>
        <TextField :model-value="s.index.image_extensions.join(' ')" :label="t('settings.extensions')" :supporting-text="envNote('HANAIKADA_INDEX__IMAGE_EXTENSIONS') ?? t('settings.extensionsHelp')" @change="save({ index: { image_extensions: list($event) } })" />
        <div class="grid">
          <TextField :model-value="s.index.watch_interval" type="number" :min="0" :label="t('settings.watchInterval')" :supporting-text="t('settings.watchIntervalHelp')" @change="save({ index: { watch_interval: num($event) } })" />
          <TextField :model-value="s.index.prompt_tag_min_count" type="number" :min="1" :label="t('settings.promptTagMin')" @change="save({ index: { prompt_tag_min_count: num($event) } })" />
        </div>
        <Switch :model-value="s.index.scan_on_start" :label="t('settings.scanOnStart')" @update:model-value="save({ index: { scan_on_start: $event } })" />
        <Switch :model-value="s.index.include_comfyui_temp" :label="t('settings.comfyTemp')" @update:model-value="save({ index: { include_comfyui_temp: $event } })" />
        <Switch :model-value="s.index.invokeai_read_db" :label="t('settings.invokeaiDb')" :supporting-text="t('settings.invokeaiDbHelp')" @update:model-value="save({ index: { invokeai_read_db: $event } })" />
        <Switch :model-value="s.index.follow_symlinks" :label="t('settings.followSymlinks')" @update:model-value="save({ index: { follow_symlinks: $event } })" />
        <p class="type-body-small muted">{{ t('settings.fts') }}: {{ meta.data.value?.fts ? t('settings.ftsOn') : t('settings.ftsOff') }}</p>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.thumbnails') }}</h2>
        <div class="grid">
          <TextField :model-value="s.thumbnails.quality" type="number" :min="1" :max="100" :label="t('settings.quality')" :supporting-text="t('settings.restartNeeded')" @change="save({ thumbnails: { quality: num($event) } }, true)" />
          <TextField :model-value="s.thumbnails.cache_max_mb" type="number" :min="16" :label="t('settings.cacheSize')" @change="save({ thumbnails: { cache_max_mb: num($event) } })" />
        </div>
        <Switch :model-value="s.thumbnails.prefer_platform_thumbnails" :label="t('settings.platformThumbs')" @update:model-value="save({ thumbnails: { prefer_platform_thumbnails: $event } })" />
        <Switch :model-value="s.thumbnails.pregenerate" :label="t('settings.pregenerate')" @update:model-value="save({ thumbnails: { pregenerate: $event } })" />
        <div class="field-row">
          <span class="type-body-medium muted">{{ cache.data.value ? t('settings.cacheUsage', { files: cache.data.value.files, size: formatBytes(cache.data.value.bytes), path: cache.data.value.path }) : '' }}</span>
          <AppButton variant="tonal" :icon="icons.Trash2" :loading="library.clearThumbnails.isPending.value" @click="clearCache">{{ t('settings.clearCache') }}</AppButton>
        </div>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.library') }} &amp; {{ t('settings.sections.content') }}</h2>
        <Switch :model-value="s.library.delete_to_trash" :label="t('settings.deleteToTrash')" :supporting-text="t('settings.deleteToTrashHelp', { where: meta.data.value?.trash_location ?? '' })" @update:model-value="save({ library: { delete_to_trash: $event } })" />
        <Switch :model-value="s.library.show_all_files" :label="t('settings.showAllFiles')" @update:model-value="save({ library: { show_all_files: $event } })" />
        <Switch :model-value="s.library.combined_view" :label="t('settings.combinedView')" :supporting-text="t('settings.combinedViewHelp')" @update:model-value="save({ library: { combined_view: $event } })" />
        <TextField :model-value="s.library.sidecar_extensions.join(' ')" :label="t('settings.sidecars')" :supporting-text="t('settings.sidecarsHelp')" @change="save({ library: { sidecar_extensions: list($event) } })" />
        <TextField :model-value="s.content.blur_tags.join(', ')" :label="t('settings.blurTags')" :supporting-text="t('settings.blurTagsHelp')" @change="save({ content: { blur_tags: list($event, /,/) } })" />
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.appearance') }}</h2>
        <div class="field-row">
          <span class="type-body-large">{{ t('settings.theme') }}</span>
          <SegmentedButton
            v-model="prefs.prefs.theme"
            :options="[
              { value: 'light', icon: icons.Sun, label: t('settings.themes.light') },
              { value: 'dark', icon: icons.Moon, label: t('settings.themes.dark') },
              { value: 'system', icon: icons.SunMoon, label: t('settings.themes.system') },
            ]"
          />
        </div>
        <label class="field-row">
          <span class="type-body-large">{{ t('settings.sourceColor') }}</span>
          <input v-model="prefs.prefs.sourceColor" type="color" class="color" :aria-label="t('settings.sourceColor')" />
        </label>
        <Slider v-model="prefs.prefs.contrast" :label="t('settings.contrast')" :min="0" :max="1" :step="0.5" ticks />
        <Slider v-model="prefs.prefs.cellSize" :label="t('settings.cellSize')" :min="96" :max="512" :step="8" />
        <div class="field-row">
          <span class="type-body-large">{{ t('settings.defaultSort') }}</span>
          <SelectField v-model="prefs.prefs.sort" :options="(['mtime', 'ctime', 'name', 'size', 'random'] as const).map((v) => ({ value: v, label: t(`sort.${v}`) }))" />
        </div>
        <div class="field-row">
          <span class="type-body-large">{{ t('settings.language') }}</span>
          <SelectField v-model="prefs.prefs.locale" :options="localeOptions" />
        </div>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.shortcuts') }}</h2>
        <p class="type-body-small muted">{{ t('settings.shortcutsHelp') }}</p>
        <div class="shortcuts">
          <button v-for="action in shortcutActions" :key="action" type="button" class="shortcut state-layer" @click="capture(action)">
            <span class="type-body-medium">{{ t(`settings.shortcuts.${action}`) }}</span>
            <span v-if="capturing === action" class="type-label-medium muted">{{ t('settings.pressKey') }}</span>
            <KeyHint v-else :keys="prefs.prefs.shortcuts[action]" />
          </button>
        </div>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.server') }}</h2>
        <div class="grid">
          <TextField :model-value="s.server.host" :label="t('settings.host')" :supporting-text="t('settings.restartNeeded')" @change="save({ server: { host: $event } }, true)" />
          <TextField :model-value="s.server.port" type="number" :label="t('settings.port')" :supporting-text="t('settings.restartNeeded')" @change="save({ server: { port: num($event) } }, true)" />
        </div>
        <TokenField
          :label="t('settings.accessToken')"
          :configured="s.server.access_token_configured"
          :save-label="t('common.save')"
          :clear-label="t('common.clear')"
          :configured-text="t('settings.tokenConfigured')"
          :not-configured-text="t('settings.accessTokenHelp')"
          @save="save({ server: { access_token: $event } })"
          @clear="save({ server: { access_token: null } })"
        />
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.about') }}</h2>
        <dl class="about type-body-medium">
          <dt class="muted">{{ t('settings.version') }}</dt>
          <dd>{{ version.data.value?.version ?? '—' }}</dd>
          <dt class="muted">{{ t('settings.dataDir') }}</dt>
          <dd>{{ s.data_dir }}</dd>
          <dt class="muted">{{ t('settings.settingsFile') }}</dt>
          <dd>{{ s.settings_file }}</dd>
          <template v-if="s.env_overrides.length">
            <dt class="muted">{{ t('settings.envOverrides') }}</dt>
            <dd>{{ s.env_overrides.join(', ') }}</dd>
          </template>
        </dl>
      </Surface>
    </template>
    <RootDialog v-model:open="rootDialog" :root="editing" />
    <ConfirmDialog
      v-model:open="removeOpen"
      :title="t('roots.removeTitle', { name: removing?.name ?? '' })"
      :message="t('roots.removeText')"
      :confirm-label="t('roots.remove')"
      :cancel-label="t('common.cancel')"
      danger
      @confirm="removeRoot"
    />
  </div>
</template>

<style scoped>
/* One column of sections, each as wide as the window allows. */
.settings { display: flex; flex-direction: column; align-items: stretch; gap: var(--app-space-4); width: 100%; padding: var(--app-space-4) var(--app-space-6) var(--app-space-8); }
.skeletons { display: flex; flex-direction: column; gap: var(--app-space-4); }
.section { display: flex; flex-direction: column; gap: var(--app-space-2); padding: var(--app-space-4) var(--app-space-6) var(--app-space-6); }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-3); flex-wrap: wrap; }
h2 { margin: 0 0 var(--app-space-2); }
.field-row { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-4); min-height: 56px; flex-wrap: wrap; }
.field-row > .muted { min-width: 0; overflow-wrap: anywhere; }
.color { width: 56px; height: 40px; padding: 0; border: 1px solid var(--md-sys-color-outline); border-radius: var(--md-sys-shape-corner-small); background: transparent; cursor: pointer; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--app-space-3); }
.root { display: flex; flex-direction: column; gap: var(--app-space-1); padding: var(--app-space-3); border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); }
.root-head { display: flex; align-items: center; gap: var(--app-space-2); flex-wrap: wrap; }
.root-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.path { overflow-wrap: anywhere; }
.root-switches { display: flex; flex-wrap: wrap; gap: 0 var(--app-space-6); }
.root-switches > * { flex: 1 1 240px; }
.shortcuts { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--app-space-2); }
.shortcut { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-2); height: 44px; padding: 0 var(--app-space-3); border: 0; border-radius: var(--md-sys-shape-corner-small); background: var(--md-sys-color-surface-container); color: var(--md-sys-color-on-surface); cursor: pointer; font: inherit; }
.about { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: var(--app-space-2) var(--app-space-4); margin: 0; }
.about dd { margin: 0; overflow-wrap: anywhere; }
p { margin: 0; }
@media (max-width: 599px) {
  .settings { padding: var(--app-space-3); }
  .section { padding: var(--app-space-4); }
}
</style>
