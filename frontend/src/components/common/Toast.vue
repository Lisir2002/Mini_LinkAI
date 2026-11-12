<script setup lang="ts">
import { useToastStore } from '../../stores/toast'
const toast = useToastStore()
</script>
<template>
  <div class="toast-layer">
    <div v-for="t in toast.items" :key="t.id" class="toast" :class="t.kind" role="status"
         @click="toast.dismiss(t.id)">{{ t.text }}</div>
  </div>
</template>
<style scoped>
.toast-layer { position: fixed; bottom: 76px; left: 50%; transform: translateX(-50%);
  z-index: 9999; display: flex; flex-direction: column; gap: 8px; align-items: center; width: 100%; max-width: 340px; }
.toast { padding: 9px 16px; border-radius: var(--r-sm); background: var(--toast-bg); color: #fff;
  font-size: var(--fs-md); cursor: pointer; box-shadow: 0 4px 16px rgba(0,0,0,.24); text-align: center; }
.toast.error { background: var(--err); }
.toast.success { background: var(--ok); }
</style>
