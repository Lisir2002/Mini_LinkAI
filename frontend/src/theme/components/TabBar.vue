<script setup lang="ts">
import AppIcon from './AppIcon.vue'
const tabs = [
  { key: 'msgs', label: '消息', icon: 'chat', to: '/msgs' },
  { key: 'rooms', label: '列表', icon: 'door-in', to: '/rooms' },
  { key: 'me', label: '我的', icon: 'user', to: '/me' },
]
defineProps<{ active: string; unread?: number }>()
</script>

<template>
  <nav class="tab-bar">
    <router-link v-for="t in tabs" :key="t.key" :to="t.to"
                 class="tab-item" :class="{ active: active === t.key }">
      <span class="tab-icon">
        <AppIcon :name="t.icon" />
        <span v-if="t.key === 'msgs' && unread" class="tab-badge">{{ unread }}</span>
      </span>
      <span class="tab-label">{{ t.label }}</span>
    </router-link>
  </nav>
</template>

<style scoped>
.tab-bar {
  position: fixed; bottom: 0; left: 50%; transform: translateX(-50%);
  width: 100%; max-width: 375px; display: flex; justify-content: space-between;
  align-items: center; padding: 6px 0 calc(6px + env(safe-area-inset-bottom));
  background: var(--surface); border-top: 1px solid var(--line); z-index: 50;
}
/* flex:1 强制三等分，任一格内容宽度变化都不影响其它格 */
.tab-item {
  flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center;
  gap: 2px; font-size: 10px; color: var(--t3); text-decoration: none; position: relative;
}
.tab-item .app-icon { width: 21px; height: 21px; }
.tab-item.active { color: var(--t1); font-weight: 600; }
.tab-item.active::after {
  content: ''; position: absolute; top: -6px; left: 50%; transform: translateX(-50%);
  width: 14px; height: 2px; background: var(--accent); border-radius: 1px;
}
.tab-icon { position: relative; display: flex; align-items: center; justify-content: center; }
.tab-badge {
  position: absolute; top: -3px; right: -7px; min-width: 14px; height: 14px; padding: 0 3px;
  border-radius: 7px; background: var(--err); color: #fff; font-size: 9px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  border: 1.5px solid var(--surface);
}
</style>
