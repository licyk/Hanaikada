<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { RouterView } from 'vue-router';
import { connectSocket, disconnectSocket } from '@/api/socket';
import ActivitySheet from '@/components/ActivitySheet.vue';
import AuthDialog from '@/components/AuthDialog.vue';
import CompareView from '@/components/CompareView.vue';
import DeleteDialog from '@/components/DeleteDialog.vue';
import NewFolderDialog from '@/components/NewFolderDialog.vue';
import RenameDialog from '@/components/RenameDialog.vue';
import TagPickerDialog from '@/components/TagPickerDialog.vue';
import TransferDialog from '@/components/TransferDialog.vue';
import Viewer from '@/components/Viewer.vue';
import { useI18n } from '@/i18n';
import { addressOf } from '@/router';
import { usePreferencesStore } from '@/stores/preferences';
import { useHostStore } from '@/stores/host';
import { useScanStore } from '@/stores/scan';
import { useUploadsStore } from '@/stores/uploads';
import { applyTheme, watchSystemTheme } from '@/theme/applyTheme';
import { AppShell, IconButton, TRANSITIONS, icons, type NavItem } from '@/ui';

const { t, locale } = useI18n();
const qc = useQueryClient();
const prefs = usePreferencesStore();
const scan = useScanStore();
const uploads = useUploadsStore();

const themeOptions = () => ({ mode: prefs.prefs.theme, sourceColor: prefs.prefs.sourceColor, contrast: prefs.prefs.contrast });
watch(() => [prefs.prefs.theme, prefs.prefs.sourceColor, prefs.prefs.contrast], () => applyTheme(themeOptions()), { immediate: true });
watch(locale, (l) => (document.documentElement.lang = l), { immediate: true });
const stopTheme = watchSystemTheme(themeOptions);

onMounted(() => {
  // Framed by the SD WebUI or ComfyUI extension: learn what it takes ("Send to …").
  useHostStore().connect();
  connectSocket(qc);
  prefs.loadFromServer();
});
onBeforeUnmount(() => {
  stopTheme();
  disconnectSocket();
});

const nav = computed<NavItem[]>(() => [
  { to: addressOf('browse'), label: t('nav.browse'), icon: icons.Folder },
  { to: addressOf('search'), label: t('nav.search'), icon: icons.Search },
  { to: addressOf('tags'), label: t('nav.tags'), icon: icons.Tags },
  { to: addressOf('stats'), label: t('nav.stats'), icon: icons.BarChart3 },
  { to: addressOf('settings'), label: t('nav.settings'), icon: icons.Settings },
]);

// Pages are kept alive (KeepAlive below) so each keeps its state while another is shown, in memory
// only. The shell's scroller is shared, so each page's offset in it is kept here and put back.
const shell = ref<InstanceType<typeof AppShell> | null>(null);
const offsets = new WeakMap<Element, number>();
const saveOffset = (el: Element) => offsets.set(el, shell.value?.content?.scrollTop ?? 0);
function restoreOffset(el: Element) {
  const content = shell.value?.content;
  if (content) content.scrollTop = offsets.get(el) ?? 0;
}
const cycleTheme = () => (prefs.prefs.theme = prefs.prefs.theme === 'light' ? 'dark' : prefs.prefs.theme === 'dark' ? 'system' : 'light');
const themeIcon = computed(() => ({ light: icons.Sun, dark: icons.Moon, system: icons.SunMoon })[prefs.prefs.theme]);
const busy = computed(() => scan.active.length > 0 || uploads.active > 0);
const activityLabel = computed(() => (scan.active.length ? `${t('scan.scanning')} · ${t('scan.chip', { n: scan.indexedNow })}` : t('nav.activity')));
</script>

<template>
  <AppShell ref="shell" :items="nav" :title="t('app.title')">
    <template #rail-top>
      <IconButton :icon="icons.Blossom" :label="t('app.title')" tonal />
    </template>
    <template #actions>
      <span v-if="scan.active.length" class="scan-note type-label-medium muted">{{ t('scan.chip', { n: scan.indexedNow }) }}</span>
      <IconButton :icon="busy ? icons.RefreshCw : icons.Waves" :spin="busy" :label="activityLabel" :badge="uploads.active || null" @click="scan.sheetOpen = true" />
      <IconButton :icon="themeIcon" :label="`${t('settings.theme')}: ${t(`settings.themes.${prefs.prefs.theme}`)}`" @click="cycleTheme" />
    </template>
    <RouterView v-slot="{ Component, route }">
      <Transition :name="TRANSITIONS.fadeThrough" mode="out-in" @before-leave="saveOffset" @enter="restoreOffset">
        <KeepAlive>
          <component :is="Component" :key="route.name" />
        </KeepAlive>
      </Transition>
    </RouterView>
  </AppShell>
  <Viewer />
  <ActivitySheet />
  <TransferDialog />
  <RenameDialog />
  <DeleteDialog />
  <TagPickerDialog />
  <NewFolderDialog />
  <CompareView />
  <AuthDialog />
</template>

<style scoped>
.scan-note { white-space: nowrap; }
@media (max-width: 599px) {
  .scan-note { display: none; }
}
</style>
