<script setup lang="ts">
import { computed, ref } from 'vue';
import { useTags } from '@/api/queries/tags';
import type { Tag } from '@/api/types';
import { useI18n } from '@/i18n';
import { Chip, TextField, icons } from '@/ui';

/** Pick tags of any type by typing part of their name. The model is a list of tag ids. */
const props = defineProps<{ label: string; known?: Tag[] }>();
const model = defineModel<number[]>({ default: () => [] });
const { t } = useI18n();
const query = ref('');
const suggestions = useTags(null, query, 12);
const byId = computed(() => new Map([...(props.known ?? []), ...(suggestions.data.value ?? [])].map((tag) => [tag.id, tag])));
const chosen = computed(() => model.value.map((id) => byId.value.get(id) ?? ({ id, name: `#${id}`, type: 'custom' } as Tag)));
const options = computed(() => (query.value ? (suggestions.data.value ?? []).filter((tag) => !model.value.includes(tag.id)) : []));

function add(tag: Tag) {
  model.value = [...model.value, tag.id];
  query.value = '';
}
const remove = (id: number) => (model.value = model.value.filter((x) => x !== id));
</script>

<template>
  <div class="tag-select">
    <TextField v-model="query" :label="label" :icon="icons.Tag" @enter="options[0] && add(options[0])" />
    <div v-if="options.length" class="options">
      <Chip v-for="tag in options" :key="tag.id" :label="tag.name" :count="tag.count" :title="t(`tags.types.${tag.type}`)" @click="add(tag)" />
    </div>
    <div v-if="chosen.length" class="chosen">
      <Chip v-for="tag in chosen" :key="tag.id" :label="tag.name" :dot="tag.color" selected removable @remove="remove(tag.id)" @click="remove(tag.id)" />
    </div>
  </div>
</template>

<style scoped>
.tag-select { display: flex; flex-direction: column; gap: var(--app-space-2); }
.options, .chosen { display: flex; flex-wrap: wrap; gap: var(--app-space-1); }
</style>
