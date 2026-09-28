<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { chunkUrl } from '@/api/client';
import { useImageByPath, useRaw } from '@/api/queries/images';
import { useCustomTags } from '@/api/queries/tags';
import type { GenerationInfo, ImageItem } from '@/api/types';
import { copyText, useImageActions } from '@/components/imageActions';
import { formatBytes, formatDate } from '@/format';
import { useI18n } from '@/i18n';
import { changedFields, diffPrompts, splitExtraNetworks } from '@/metadata/infotext';
import { samplerLabel } from '@/metadata/samplers';
import { encodeQuery } from '@/search/url';
import { type InfoTab, usePreferencesStore } from '@/stores/preferences';
import { useDialogsStore } from '@/stores/dialogs';
import { AppIcon, Chip, DataList, ExpansionPanel, IconButton, ProgressCircle, Tabs, TRANSITIONS, icons, useSnackbar } from '@/ui';

/**
 * What an image says about how it was made: the normalised parameters, the prompt with its change
 * from the previous image, every raw chunk, and the file's other entries.
 */
const props = defineProps<{ item: ImageItem; previous?: ImageItem | null }>();
const { t, platformLabel, locale } = useI18n();
const prefs = usePreferencesStore();
const router = useRouter();
const snackbar = useSnackbar();
const dialogs = useDialogsStore();
const actions = useImageActions();
const customTags = useCustomTags();

// Only images are indexed and carry metadata; a video, audio or other file shows its file facts.
const isImage = computed(() => props.item.kind === 'image');
const detail = useImageByPath(() => (isImage.value ? props.item.rootId : null), () => props.item.path, () => props.item.version);
const previousDetail = useImageByPath(
  () => (prefs.prefs.infoTab === 'prompt' && props.previous?.kind === 'image' ? props.previous.rootId : null),
  () => props.previous?.path ?? null,
  () => props.previous?.version ?? null,
);
const d = computed(() => detail.data.value);
const info = computed<GenerationInfo | null>(() => d.value?.info ?? null);
const raw = useRaw(() => d.value?.record.id ?? null, () => prefs.prefs.infoTab === 'raw' || prefs.prefs.infoTab === 'info');

const TAB_ORDER: InfoTab[] = ['parameters', 'prompt', 'raw', 'info'];
const tabs = computed(() => TAB_ORDER.map((value) => ({ value, label: t(`info.tabs.${value}`) })));
// A tab's content slides the way the tabs moved: forward to one on the right, back to one on the left.
const axisDir = ref(1);
watch(
  () => prefs.prefs.infoTab,
  (next, prev) => (axisDir.value = TAB_ORDER.indexOf(next) >= TAB_ORDER.indexOf(prev) ? 1 : -1),
);

const num = (v: number | null | undefined) => (v === null || v === undefined ? null : Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000));
const rows = computed(() => {
  const i = info.value;
  if (!i) return [];
  const sampler = [i.sampler, i.scheduler].filter(Boolean).join(' · ');
  const norm = i.sampler_norm && samplerLabel(i.sampler_norm) !== i.sampler ? ` (${samplerLabel(i.sampler_norm)})` : '';
  return [
    { label: t('info.seed'), value: i.seed === null || i.seed === undefined ? null : String(i.seed), mono: true },
    { label: t('info.steps'), value: i.steps },
    { label: t('info.cfg'), value: num(i.cfg_scale) },
    { label: t('info.distilledCfg'), value: num(i.distilled_cfg) },
    { label: t('info.cfgRescale'), value: num(i.cfg_rescale) },
    { label: t('info.sampler'), value: sampler ? sampler + norm : null },
    { label: t('info.size'), value: i.width && i.height ? `${i.width} × ${i.height}` : null },
    { label: t('info.model'), value: i.model ? i.model.name + (i.model.hash ? `  [${i.model.hash_kind ?? t('info.hash')}: ${i.model.hash.slice(0, 16)}]` : '') : null },
    { label: t('info.vae'), value: i.vae?.name },
    { label: t('info.clipSkip'), value: i.clip_skip },
    { label: t('info.denoise'), value: num(i.denoise) },
    { label: t('info.mode'), value: i.mode ? t(`modes.${i.mode}`) : null },
    { label: t('info.family'), value: i.family },
    { label: t('info.platform'), value: `${platformLabel(i.platform)}${i.platform_version ? ` ${i.platform_version}` : ''}` },
    { label: t('info.sources'), value: i.sources.join(', ') },
  ];
});
const passRows = computed(() =>
  (info.value?.passes ?? []).map((p) => ({
    label: t(`info.passKinds.${p.kind}`),
    value: Object.entries(p)
      .filter(([k, v]) => k !== 'kind' && v !== null && v !== undefined && k !== 'model')
      .map(([k, v]) => `${k} ${typeof v === 'number' ? num(v) : v}`)
      .concat(p.model ? [`model ${p.model.name}`] : [])
      .join(' · '),
  })),
);
const controlRows = computed(() =>
  (info.value?.controls ?? []).map((c) => ({
    label: String((c as Record<string, unknown>).type ?? 'control'),
    value: Object.entries(c as Record<string, unknown>)
      .filter(([k]) => k !== 'type' && k !== 'node')
      .map(([k, v]) => `${k} ${v}`)
      .join(' · '),
  })),
);
const extraRows = computed(() => Object.entries(info.value?.extras ?? {}).map(([label, value]) => ({ label, value: value === null ? '—' : String(value) })));

const tagColor = (id: number) => customTags.data.value?.find((tag) => tag.id === id)?.color ?? null;
const imageTags = computed(() => (d.value?.tags ?? []).filter((tag) => tag.type === 'custom' || tag.type === 'board'));
const favorite = computed(() => d.value?.tags.some((tag) => tag.type === 'custom' && tag.name === 'favorite') ?? false);

async function copy(text: string | null | undefined) {
  if (!text) return;
  await copyText(text);
  snackbar.show(t('common.copied'));
}

const selectedText = ref('');
function captureSelection() {
  selectedText.value = window.getSelection()?.toString().trim() ?? '';
}
function searchSelection(text: string) {
  if (text) router.push({ name: 'search', query: { q: encodeQuery({ text, text_in: ['prompt'] }) } });
}

const promptParts = computed(() => splitExtraNetworks(d.value?.prompt ?? ''));
const diff = computed(() => {
  const prev = previousDetail.data.value;
  if (!prev || !d.value) return null;
  return { fields: changedFields(prev.info, d.value.info), prompt: diffPrompts(prev.prompt, d.value.prompt), negative: diffPrompts(prev.info.negative_prompt, d.value.info.negative_prompt) };
});

function pretty(value: string): string {
  const text = value.trim();
  if (!text.startsWith('{') && !text.startsWith('[')) return value;
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return value;
  }
}
const isJson = (value: string) => /^\s*[{[]/.test(value);
// Short text chunks start open; JSON graphs, often hundreds of kilobytes, open on request.
const opened = ref(new Map<string, boolean>());
const isOpen = (key: string, value: string) => opened.value.get(key) ?? (value.length < 4000 && !isJson(value));
const setOpen = (key: string, value: boolean) => (opened.value = new Map(opened.value).set(key, value));
</script>

<template>
  <section v-if="!isImage" class="info-panel">
    <div class="body">
      <DataList
        :rows="[
          { label: t('info.file'), value: item.name },
          { label: t('info.path'), value: `${item.rootId}:${item.path}` },
          { label: t('info.format'), value: [item.name.split('.').pop()?.toUpperCase(), t(`info.kinds.${item.kind}`)].filter(Boolean).join(' · ') },
          { label: t('info.fileSize'), value: formatBytes(item.size) },
          { label: t('info.modified'), value: formatDate(item.mtime, locale) },
        ]"
      />
    </div>
  </section>
  <section v-else class="info-panel">
    <Tabs v-model="prefs.prefs.infoTab" :tabs="tabs" />
    <div class="body">
      <div v-if="detail.isLoading.value" class="loading"><ProgressCircle :size="32" /><span class="muted type-body-medium">{{ t('info.notIndexed') }}</span></div>
      <p v-else-if="detail.error.value" class="error type-body-medium">{{ (detail.error.value as Error).message }}</p>

      <template v-else-if="d && info">
        <!-- The tabs slide along the shared x axis; the stage keeps the leaving one inside the padding. -->
        <div class="stage" :style="{ '--axis-dir': axisDir }">
          <Transition :name="TRANSITIONS.sharedAxisX">
            <!-- Parameters -->
            <div v-if="prefs.prefs.infoTab === 'parameters'" class="tab">
              <div class="tags">
                <Chip :label="t('menu.favorite')" :icon="icons.Heart" :selected="favorite" @click="actions.setFavorite([item], !favorite)" />
                <Chip v-for="tag in imageTags.filter((x) => x.name !== 'favorite')" :key="tag.id" :label="tag.name" :dot="tagColor(tag.id)" selected @click="dialogs.openTags([item])" />
                <Chip :label="t('tags.add')" :icon="icons.Plus" @click="dialogs.openTags([item])" />
              </div>
              <p v-if="d.parse_error" class="error type-body-small">{{ t('info.parseError', { error: d.parse_error }) }}</p>
              <p v-if="info.platform === 'none'" class="muted type-body-medium">{{ t('info.noMetadata') }}</p>
              <div v-if="d.prompt" class="block">
                <div class="block-head">
                  <span class="type-label-large block-title">{{ t('info.prompt') }}</span>
                  <IconButton :icon="icons.Copy" :label="t('info.copy')" @click="copy(d.prompt)" />
                  <IconButton v-if="selectedText" :icon="icons.Search" :label="t('info.searchThis')" @click="searchSelection(selectedText)" />
                </div>
                <p class="prompt type-body-medium" @mouseup="captureSelection" @keyup="captureSelection">{{ d.prompt }}</p>
              </div>
              <div v-if="info.negative_prompt" class="block">
                <div class="block-head">
                  <span class="type-label-large block-title">{{ t('info.negative') }}</span>
                  <IconButton :icon="icons.Copy" :label="t('info.copy')" @click="copy(info.negative_prompt)" />
                </div>
                <p class="prompt negative type-body-medium">{{ info.negative_prompt }}</p>
              </div>
              <div v-if="info.prompts.length > 1" class="block">
                <span class="type-label-large">{{ t('info.prompts') }}</span>
                <p v-for="(p, i) in info.prompts.slice(1)" :key="i" class="prompt type-body-small">{{ p }}</p>
              </div>
              <DataList :rows="rows" />
              <div v-if="info.loras.length" class="block">
                <span class="type-label-large">{{ t('info.loras') }}</span>
                <div class="loras">
                  <Chip v-for="l in info.loras" :key="l.name" :label="`${l.name}${l.weight !== null ? ` · ${num(l.weight)}` : ''}${l.weight_clip !== null && l.weight_clip !== l.weight ? `/${num(l.weight_clip)}` : ''}`" :title="l.hash ?? l.name" @click="searchSelection(l.name)" />
                </div>
              </div>
              <div v-if="passRows.length" class="block"><span class="type-label-large">{{ t('info.passes') }}</span><DataList :rows="passRows" /></div>
              <div v-if="controlRows.length" class="block"><span class="type-label-large">{{ t('info.controls') }}</span><DataList :rows="controlRows" /></div>
              <div v-if="info.warnings.length" class="block">
                <span class="type-label-large">{{ t('info.warnings') }}</span>
                <p v-for="w in info.warnings" :key="w" class="muted type-body-small">{{ w }}</p>
              </div>
              <ExpansionPanel v-if="extraRows.length" :label="t('info.extras')" :supporting-text="String(extraRows.length)">
                <DataList :rows="extraRows.map((r) => ({ ...r, mono: true }))" />
              </ExpansionPanel>
            </div>

            <!-- Prompt and the change from the previous image -->
            <div v-else-if="prefs.prefs.infoTab === 'prompt'" class="tab">
              <div class="block">
                <div class="block-head">
                  <span class="type-label-large block-title">{{ t('info.prompt') }}</span>
                  <IconButton :icon="icons.Copy" :label="t('info.copy')" @click="copy(d.prompt)" />
                </div>
                <p class="prompt type-body-medium">
                  <template v-for="(part, i) in promptParts" :key="i"><mark v-if="part.tag" class="lora">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template>
                </p>
              </div>
              <div class="block">
                <span class="type-label-large">{{ t('info.changedFromPrevious') }}</span>
                <p v-if="!previous" class="muted type-body-small">{{ t('info.noPrevious') }}</p>
                <ProgressCircle v-else-if="previousDetail.isLoading.value" :size="24" />
                <template v-else-if="diff">
                  <p v-if="!diff.fields.length" class="muted type-body-small">{{ t('info.nothingChanged') }}</p>
                  <div v-else class="loras"><Chip v-for="f in diff.fields" :key="f" :label="f" selected /></div>
                  <p class="tokens type-body-small">
                    <span v-for="(token, i) in diff.prompt" :key="i" class="token" :class="token.change" :title="token.change === 'same' ? undefined : t(`info.${token.change}`)">{{ token.text }}</span>
                  </p>
                  <p v-if="diff.negative.some((x) => x.change !== 'same')" class="tokens type-body-small">
                    <span class="muted">{{ t('info.negative') }}: </span>
                    <span v-for="(token, i) in diff.negative.filter((x) => x.change !== 'same')" :key="i" class="token" :class="token.change">{{ token.text }}</span>
                  </p>
                </template>
              </div>
            </div>

            <!-- Raw chunks -->
            <div v-else-if="prefs.prefs.infoTab === 'raw'" class="tab">
              <ProgressCircle v-if="raw.isLoading.value" :size="28" />
              <p v-else-if="!raw.data.value?.chunks.length" class="muted type-body-medium">{{ t('info.noMetadata') }}</p>
              <ExpansionPanel v-for="chunk in raw.data.value?.chunks ?? []" :key="chunk.key" :label="chunk.key" :supporting-text="`${chunk.source ?? ''} · ${formatBytes(chunk.value.length)}`" :open="isOpen(chunk.key, chunk.value)" @update:open="setOpen(chunk.key, $event)">
                <template #trailing>
                  <a class="download" :href="chunkUrl(d.record.id, chunk.key)" :title="t('info.downloadChunk')" @click.stop><AppIcon :icon="icons.Download" :size="20" /></a>
                </template>
                <p v-if="chunk.truncated" class="muted type-body-small">{{ t('info.truncated') }}</p>
                <pre class="raw">{{ pretty(chunk.value) }}</pre>
              </ExpansionPanel>
            </div>

            <!-- File -->
            <div v-else class="tab">
              <DataList
                :rows="[
                  { label: t('info.file'), value: d.record.name },
                  { label: t('info.path'), value: `${d.record.root_id}:${d.record.path}` },
                  { label: t('info.fileSize'), value: formatBytes(d.record.size) },
                  { label: t('info.dimensions'), value: d.record.width ? `${d.record.width} × ${d.record.height}` : null },
                  { label: t('info.format'), value: [raw.data.value?.format ?? d.record.format, raw.data.value?.mode].filter(Boolean).join(' · ') },
                  { label: t('info.modified'), value: formatDate(d.record.mtime, locale) },
                  { label: t('info.companions'), value: d.companions.join('\n') },
                  { label: t('info.sidecars'), value: raw.data.value?.sidecars.join('\n') },
                ]"
              />
              <DataList v-if="raw.data.value" :rows="Object.entries(raw.data.value.info).map(([label, value]) => ({ label, value }))" />
            </div>
          </Transition>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.info-panel { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--app-space-3) var(--app-space-4) var(--app-space-6); }
/* Clipped sideways so a tab sliding in or out never shows a horizontal scrollbar. */
.stage { position: relative; overflow-x: clip; }
.tab { display: flex; flex-direction: column; gap: var(--app-space-4); }
.loading { display: flex; align-items: center; gap: var(--app-space-3); padding: var(--app-space-4) 0; }
.error { color: var(--md-sys-color-error); margin: 0; overflow-wrap: anywhere; }
.tags, .loras { display: flex; flex-wrap: wrap; gap: var(--app-space-2); }
.block { display: flex; flex-direction: column; gap: var(--app-space-1); min-width: 0; }
.block-head { display: flex; align-items: center; gap: var(--app-space-1); min-height: 40px; }
/* The buttons sit right after the title (an IconButton's root is a span too: select the title by class). */
.block-title { min-width: 0; }
.prompt {
  margin: 0; padding: var(--app-space-3); white-space: pre-wrap; overflow-wrap: anywhere; user-select: text;
  border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container-high);
}
.negative { background: var(--md-sys-color-surface-container); color: var(--md-sys-color-on-surface-variant); }
.lora { padding: 0 2px; border-radius: var(--md-sys-shape-corner-extra-small); background: var(--md-sys-color-tertiary-container); color: var(--md-sys-color-on-tertiary-container); }
.tokens { display: flex; flex-wrap: wrap; gap: var(--app-space-1); margin: var(--app-space-2) 0 0; }
.token { padding: 1px var(--app-space-1); border-radius: var(--md-sys-shape-corner-extra-small); background: var(--md-sys-color-surface-container-high); }
.token.added { background: var(--md-sys-color-primary-container); color: var(--md-sys-color-on-primary-container); }
.token.removed { background: var(--md-sys-color-error-container); color: var(--md-sys-color-on-error-container); text-decoration: line-through; }
.raw {
  margin: 0; max-height: 480px; overflow: auto; padding: var(--app-space-3); white-space: pre-wrap; overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: var(--md-sys-typescale-body-small-size);
  border-radius: var(--md-sys-shape-corner-small); background: var(--md-sys-color-surface-container);
}
.download { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 50%; color: inherit; }
.download:hover { background: color-mix(in srgb, currentColor calc(var(--md-sys-state-hover-state-layer-opacity) * 100%), transparent); }
p { margin: 0; }
</style>
