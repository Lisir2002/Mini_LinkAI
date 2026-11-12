<script setup lang="ts">
import AppIcon from './AppIcon.vue'
defineProps<{ icon?: string; title: string; desc?: string }>()
</script>
<template>
  <div class="empty">
    <AppIcon :name="icon ?? 'tray'" />
    <div class="empty-title">{{ title }}</div>
    <div v-if="desc" class="empty-desc">{{ desc }}</div>
    <slot />
  </div>
</template>
<style scoped>
.empty { display: flex; flex-direction: column; align-items: center; padding: 48px 16px; color: var(--t4); }
.empty .app-icon { width: 48px; height: 48px; }
.empty-title { font-size: var(--fs-lg); color: var(--t3); margin-top: 12px; }
.empty-desc { font-size: var(--fs-sm); margin-top: 6px; }
</style>
