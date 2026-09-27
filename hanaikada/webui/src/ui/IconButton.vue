<script setup lang="ts">
import '@material/web/iconbutton/icon-button.js';
import '@material/web/iconbutton/filled-tonal-icon-button.js';
import type { Component } from 'vue';
import AppIcon from '@/ui/AppIcon.vue';
import Badge from '@/ui/Badge.vue';

withDefaults(defineProps<{ icon: Component; label: string; tonal?: boolean; disabled?: boolean; badge?: number | string | null; spin?: boolean }>(), { badge: null });
defineEmits<{ click: [MouseEvent] }>();
</script>

<template>
  <span class="icon-button-wrap" :title="label">
    <component :is="tonal ? 'md-filled-tonal-icon-button' : 'md-icon-button'" :disabled.prop="disabled" :aria-label="label" @click="$emit('click', $event)">
      <AppIcon :icon="icon" :size="24" :spin="spin" />
    </component>
    <Badge v-if="badge !== null && badge !== 0" class="badge" :value="badge" />
  </span>
</template>

<style scoped>
.icon-button-wrap { position: relative; display: inline-flex; }
.badge { position: absolute; top: 4px; right: 4px; pointer-events: none; }
</style>
