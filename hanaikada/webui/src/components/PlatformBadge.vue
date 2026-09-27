<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from '@/i18n';

/** A one-letter mark for the platform that made an image, with its full name as a tooltip. */
const props = defineProps<{ platform: string | null | undefined }>();
const { platformLabel } = useI18n();
const letter = computed(() => ({ 'sd-webui': 'W', comfyui: 'C', invokeai: 'I', novelai: 'N' })[props.platform ?? ''] ?? '');
</script>

<template>
  <span v-if="letter" class="platform type-label-small" :class="platform" :title="platformLabel(platform)" :aria-label="platformLabel(platform)">{{ letter }}</span>
</template>

<style scoped>
.platform {
  display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: var(--md-sys-shape-corner-extra-small);
  font-weight: 700; background: var(--md-sys-color-surface-container-highest); color: var(--md-sys-color-on-surface-variant);
}
.sd-webui { background: var(--md-sys-color-primary-container); color: var(--md-sys-color-on-primary-container); }
.comfyui { background: var(--md-sys-color-tertiary-container); color: var(--md-sys-color-on-tertiary-container); }
.invokeai { background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); }
.novelai { background: var(--md-sys-color-inverse-surface); color: var(--md-sys-color-inverse-on-surface); }
</style>
