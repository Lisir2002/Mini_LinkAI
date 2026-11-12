<script setup lang="ts">
import AppIcon from './AppIcon.vue'
defineProps<{ icon?: string; tone?: 'default' | 'accent'; active?: boolean }>()
defineEmits<{ click: [] }>()
</script>
<template>
  <button type="button" class="chip" :class="{ accent: tone === 'accent', active }" @click="$emit('click')">
    <AppIcon :name="icon" v-if="icon" /><slot />
  </button>
</template>
<style scoped>
.chip { display: inline-flex; align-items: center; gap: 3px; padding: 4px 9px; border-radius: 20px;
  font-size: var(--fs-cap); font-weight: 600; cursor: pointer; white-space: nowrap; flex-shrink: 0;
  border: 1px solid var(--line); color: var(--t2); background: var(--surface-2); }
.chip .app-icon { width: 14px; height: 14px; }
.chip.accent { background: var(--accent-soft); border-color: transparent; color: var(--accent); }
.chip.active { background: var(--t1); color: var(--bg); border-color: var(--t1); }
</style>
