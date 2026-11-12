<script setup lang="ts">
import AppIcon from '../../components/common/AppIcon.vue'
defineProps<{ icon?: string; text?: string; tone?: 'ai' | 'room' | 'sys'; online?: boolean; size?: number }>()
</script>
<template>
  <div class="avatar" :class="tone ?? 'sys'" :style="{ width: (size ?? 40) + 'px', height: (size ?? 40) + 'px' }">
    <AppIcon :name="icon" v-if="icon" />
    <span v-else class="initial">{{ (text ?? '?').slice(0, 1) }}</span>
    <i v-if="online" class="dot" />
  </div>
</template>
<style scoped>
.avatar { border-radius: var(--r-md); flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  position: relative; background: var(--surface-2); border: 1px solid var(--line); }
.avatar .app-icon { width: 21px; height: 21px; }
.avatar.ai { color: var(--accent); }
.avatar.room { color: var(--t1); }
.avatar.sys { color: var(--t3); }
.initial { font-size: var(--fs-lg); font-weight: 700; color: var(--t2); }
.dot { position: absolute; right: -2px; bottom: -2px; width: 10px; height: 10px; border-radius: 50%;
  background: var(--ok); border: 2px solid var(--surface); }
</style>
