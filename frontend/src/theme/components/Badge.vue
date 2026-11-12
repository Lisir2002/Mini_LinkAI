<script setup lang="ts">
defineProps<{ count?: number; muted?: boolean; dot?: boolean }>()
</script>
<template>
  <span v-if="dot" class="badge dot" />
  <span v-else-if="count" class="badge" :class="{ muted }">{{ count > 99 ? '99+' : count }}</span>
</template>
<style scoped>
.badge { min-width: 17px; height: 17px; padding: 0 5px; border-radius: 9px; background: var(--err);
  color: #fff; font-size: 10px; font-weight: 700; display: inline-flex; align-items: center;
  justify-content: center; flex-shrink: 0; }
.badge.muted { background: var(--t4); }
.badge.dot { min-width: 7px; width: 7px; height: 7px; padding: 0; }
</style>
