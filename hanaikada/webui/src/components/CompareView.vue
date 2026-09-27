<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { fileUrl } from '@/api/client';
import { useImageByPath } from '@/api/queries/images';
import { useI18n } from '@/i18n';
import { changedFields, diffPrompts } from '@/metadata/infotext';
import { useDialogsStore } from '@/stores/dialogs';
import { Chip, IconButton, icons } from '@/ui';

/**
 * Two images one over the other with a divider to drag across, and what differs between them:
 * the changed parameters and a token diff of the prompts.
 */
const dialogs = useDialogsStore();
const { t } = useI18n();
const pair = computed(() => dialogs.compare?.items ?? null);
const left = computed(() => pair.value?.[0] ?? null);
const right = computed(() => pair.value?.[1] ?? null);
const a = useImageByPath(() => left.value?.rootId ?? null, () => left.value?.path ?? null, () => left.value?.version ?? null);
const b = useImageByPath(() => right.value?.rootId ?? null, () => right.value?.path ?? null, () => right.value?.version ?? null);
const split = ref(50);
const frame = ref<HTMLElement | null>(null);

const diff = computed(() => {
  if (!a.data.value || !b.data.value) return null;
  return { fields: changedFields(a.data.value.info, b.data.value.info), prompt: diffPrompts(a.data.value.prompt, b.data.value.prompt) };
});

function drag(event: PointerEvent) {
  const rect = frame.value?.getBoundingClientRect();
  if (!rect) return;
  split.value = Math.min(100, Math.max(0, ((event.clientX - rect.left) / rect.width) * 100));
}
function start(event: PointerEvent) {
  drag(event);
  window.addEventListener('pointermove', drag);
  window.addEventListener('pointerup', stop);
}
function stop() {
  window.removeEventListener('pointermove', drag);
  window.removeEventListener('pointerup', stop);
}
const onKey = (e: KeyboardEvent) => e.key === 'Escape' && (dialogs.compare = null);
watch(pair, (v) => (v ? document.addEventListener('keydown', onKey) : document.removeEventListener('keydown', onKey)));
onBeforeUnmount(() => {
  stop();
  document.removeEventListener('keydown', onKey);
});
</script>

<template>
  <Teleport to="body">
    <Transition name="scrim">
      <div v-if="left && right" class="compare" role="dialog" aria-modal="true" :aria-label="t('selection.compare')">
        <header class="bar">
          <IconButton :icon="icons.X" :label="t('common.close')" @click="dialogs.compare = null" />
          <span class="type-title-medium name">{{ left.name }}</span>
          <span class="type-title-medium vs">↔</span>
          <span class="type-title-medium name">{{ right.name }}</span>
        </header>
        <div ref="frame" class="frame" @pointerdown="start">
          <img :src="fileUrl(right.rootId, right.path, right.version)" alt="" draggable="false" />
          <img :src="fileUrl(left.rootId, left.path, left.version)" alt="" class="top" draggable="false" :style="{ clipPath: `inset(0 ${100 - split}% 0 0)` }" />
          <div class="divider" :style="{ left: `${split}%` }"><span class="handle" /></div>
        </div>
        <footer v-if="diff" class="diff">
          <div class="chips"><Chip v-for="f in diff.fields" :key="f" :label="f" selected /><span v-if="!diff.fields.length" class="type-body-small">{{ t('info.nothingChanged') }}</span></div>
          <p class="tokens type-body-small">
            <span v-for="(token, i) in diff.prompt.filter((x) => x.change !== 'same')" :key="i" class="token" :class="token.change">{{ token.text }}</span>
          </p>
        </footer>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.compare {
  position: fixed; inset: 0; z-index: 46; display: flex; flex-direction: column;
  background: color-mix(in srgb, var(--md-sys-color-scrim) 94%, var(--md-sys-color-surface)); color: var(--md-sys-color-inverse-on-surface);
  --md-icon-button-icon-color: var(--md-sys-color-inverse-on-surface);
}
.bar { display: flex; align-items: center; gap: var(--app-space-2); min-height: 56px; padding: 0 var(--app-space-2); }
.name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vs { opacity: 0.6; }
.frame { position: relative; flex: 1; min-height: 0; margin: 0 var(--app-space-4); cursor: ew-resize; touch-action: none; user-select: none; }
.frame img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
.divider { position: absolute; top: 0; bottom: 0; width: 2px; translate: -1px 0; background: var(--md-sys-color-primary); pointer-events: none; }
.handle { position: absolute; top: 50%; left: 50%; translate: -50% -50%; width: 16px; height: 48px; border-radius: var(--md-sys-shape-corner-full); background: var(--md-sys-color-primary); }
.diff { max-height: 30vh; overflow: auto; padding: var(--app-space-3) var(--app-space-4); background: var(--md-sys-color-surface-container-low); color: var(--md-sys-color-on-surface); }
.chips { display: flex; flex-wrap: wrap; gap: var(--app-space-2); align-items: center; }
.tokens { display: flex; flex-wrap: wrap; gap: var(--app-space-1); margin: var(--app-space-2) 0 0; }
.token { padding: 1px var(--app-space-1); border-radius: var(--md-sys-shape-corner-extra-small); }
.token.added { background: var(--md-sys-color-primary-container); color: var(--md-sys-color-on-primary-container); }
.token.removed { background: var(--md-sys-color-error-container); color: var(--md-sys-color-on-error-container); text-decoration: line-through; }
</style>
