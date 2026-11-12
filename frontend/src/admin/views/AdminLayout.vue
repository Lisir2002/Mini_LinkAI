<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
const route = useRoute()
const router = useRouter()
const navs = [
  { key: 'channels', label: '接口配置', icon: 'sliders' },
  { key: 'models', label: '模型注册表', icon: 'grid' },
  { key: 'invites', label: '邀请码', icon: 'key' },
  { key: 'settings', label: '系统设置', icon: 'gear' },
  { key: 'stats', label: '数据统计', icon: 'pulse' },
  { key: 'experiments', label: 'A/B 实验', icon: 'split' },
]
const current = computed(() => route.path.split('/')[2] ?? 'channels')
</script>
<template>
  <div class="admin">
    <aside class="side">
      <div class="brand"><AppIcon name="brand-chat" /><b>控制台</b></div>
      <button v-for="n in navs" :key="n.key" class="nav" :class="{ on: current === n.key }"
              @click="router.push(`/admin/${n.key}`)">
        <AppIcon :name="n.icon" /><span>{{ n.label }}</span>
      </button>
      <button class="nav back" @click="router.push('/me')">
        <AppIcon name="back" /><span>返回我的</span>
      </button>
    </aside>
    <main class="content"><slot /></main>
    <nav class="mtabs">
      <button v-for="n in navs" :key="n.key" class="mt" :class="{ on: current === n.key }"
              @click="router.push(`/admin/${n.key}`)">
        <AppIcon :name="n.icon" /><span>{{ n.label }}</span>
      </button>
    </nav>
  </div>
</template>
<style scoped>
.admin { max-width: 375px; margin: 0 auto; min-height: 100dvh; background: var(--bg);
  display: flex; flex-direction: column; }
.side { display: none; }
.content { flex: 1; min-width: 0; padding-bottom: 68px; }
.mtabs { position: fixed; bottom: 0; left: 50%; transform: translateX(-50%); width: 100%; max-width: 375px;
  display: flex; background: var(--surface); border-top: 1px solid var(--line); z-index: 50;
  padding-bottom: env(safe-area-inset-bottom); }
.mt { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 7px 0; background: none; border: none; cursor: pointer; font-size: 10px; color: var(--t3); }
.mt .app-icon { width: 20px; height: 20px; }
.mt.on { color: var(--accent); font-weight: 700; }
@media (min-width: 1024px) {
  .admin { max-width: none; flex-direction: row; }
  .side { display: flex; flex-direction: column; gap: 4px; width: 216px; flex-shrink: 0;
    background: var(--surface); border-right: 1px solid var(--line); padding: 16px 12px; min-height: 100dvh; }
  .brand { display: flex; align-items: center; gap: 8px; padding: 4px 8px 14px; font-size: var(--fs-lg); }
  .brand .app-icon { color: var(--accent); }
  .nav { display: flex; align-items: center; gap: 8px; padding: 9px 10px; border: none; border-radius: var(--r-sm);
    background: none; color: var(--t2); font-size: var(--fs-md); cursor: pointer; text-align: left; }
  .nav.on { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
  .nav.back { margin-top: auto; color: var(--t3); }
  .content { padding-bottom: 24px; }
  .mtabs { display: none; }
}
</style>
