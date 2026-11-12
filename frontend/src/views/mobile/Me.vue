<script setup lang="ts">
import AppIcon from '../../components/common/AppIcon.vue'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import NavBar from '../../components/common/NavBar.vue'
import TabBar from '../../components/common/TabBar.vue'
import Switch from '../../components/common/Switch.vue'
import Avatar from '../../components/common/Avatar.vue'
import { request } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import { useThemeStore } from '../../stores/theme'
import { useToastStore } from '../../stores/toast'

interface Quota {
  msg_limit: number; token_limit: number; tokens_used: number; ai_calls: number
  cost_today: number; cost_month: number; reset_in_seconds: number
}
const auth = useAuthStore()
const theme = useThemeStore()
const toast = useToastStore()
const router = useRouter()
const quota = ref<Quota | null>(null)
const dark = ref(theme.theme === 'dark')

function pct(used: number, limit: number) { return Math.min(100, Math.round((used / Math.max(limit, 1)) * 100)) }
function hhmmss(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
  return `${h} 小时 ${m} 分`
}
async function load() {
  try {
    const me = await request<any>('/api/auth/me')
    auth.setUser(me.data)
    quota.value = (await request<Quota>('/api/quota/me')).data
  } catch (e: any) { toast.show(e.message ?? '加载失败', 'error') }
}
function toggleTheme() { theme.toggle(); dark.value = theme.theme === 'dark' }
async function logout() {
  try { await request('/api/auth/logout', { method: 'POST' }) } catch { /* 本地仍要清 */ }
  auth.logout()
  toast.show('已退出登录')
  await router.push('/login')
}
onMounted(load)
</script>

<template>
  <div class="app-container">
    <NavBar title="我的">
      <template #right>
        <button class="icon-btn" aria-label="切换主题" @click="toggleTheme">
          <AppIcon :name="dark ? 'sun' : 'moon'" />
        </button>
      </template>
    </NavBar>

    <div class="me-header">
      <Avatar icon="user" tone="ai" :size="52" />
      <div class="who">
        <div class="name">{{ auth.user?.nickname }}
          <span v-if="auth.user?.role === 'admin'" class="tag">管理员</span>
        </div>
        <div class="sub">{{ auth.user?.email }} · ID {{ auth.user?.id }}</div>
      </div>
    </div>

    <section v-if="quota" class="card quota">
      <header><b>今日用量</b><small>{{ hhmmss(quota.reset_in_seconds) }}后重置</small></header>
      <div class="row">
        <div class="lab"><span>Token 消耗</span><span><b>{{ quota.tokens_used.toLocaleString() }}</b> / {{ quota.token_limit.toLocaleString() }}</span></div>
        <div class="track"><i :style="{ width: pct(quota.tokens_used, quota.token_limit) + '%' }" /></div>
      </div>
      <div class="row">
        <div class="lab"><span>AI 调用次数</span><span><b>{{ quota.ai_calls }}</b> 次</span></div>
        <div class="track"><i :style="{ width: pct(quota.ai_calls, quota.msg_limit) + '%' }" /></div>
      </div>
      <div class="row">
        <div class="lab"><span>本月成本</span><span><b>¥{{ quota.cost_month.toFixed(4) }}</b></span></div>
        <div class="track"><i class="warn" :style="{ width: pct(quota.cost_month, 200) + '%' }" /></div>
      </div>
    </section>

    <template v-if="auth.user?.role === 'admin'">
      <div class="sec">管理</div>
      <nav class="card menu">
        <router-link to="/admin/channels" class="mi">
          <span class="ico accent"><AppIcon name="sliders" /></span>
          <span class="txt"><b>模型接口配置</b><small>协议驱动的渠道管理</small></span>
          <AppIcon name="chevron-right" class="arrow" />
        </router-link>
        <router-link to="/admin/models" class="mi">
          <span class="ico accent"><AppIcon name="grid" /></span>
          <span class="txt"><b>模型注册表</b><small>对外模型名与渠道绑定</small></span>
          <AppIcon name="chevron-right" class="arrow" />
        </router-link>
        <router-link to="/admin/invites" class="mi">
          <span class="ico"><AppIcon name="key" /></span>
          <span class="txt"><b>邀请码发放</b><small>批量生成与作废</small></span>
          <AppIcon name="chevron-right" class="arrow" />
        </router-link>
        <router-link to="/admin/settings" class="mi">
          <span class="ico"><AppIcon name="gear" /></span>
          <span class="txt"><b>系统设置</b><small>配额、注册方式与内容安全</small></span>
          <AppIcon name="chevron-right" class="arrow" />
        </router-link>
      </nav>
    </template>

    <div class="sec">偏好与账号</div>
    <div class="card menu">
      <div class="mi">
        <span class="ico"><AppIcon name="contrast" /></span>
        <span class="txt"><b>夜间主题</b><small>默认白天，可随时切换</small></span>
        <Switch v-model="dark" @update:model-value="toggleTheme" />
      </div>
      <router-link to="/password" class="mi">
        <span class="ico"><AppIcon name="lock" /></span>
        <span class="txt"><b>修改密码</b><small>修改后其他设备需重新登录</small></span>
        <AppIcon name="chevron-right" class="arrow" />
      </router-link>
    </div>

    <button class="logout" @click="logout">退出登录</button>
    <p class="foot">AI 聊天室 · 内容由 AI 生成，仅供参考</p>
    <div class="pad-bottom" />
    <TabBar active="me" />
  </div>
</template>

<style scoped>
.icon-btn { background: none; border: none; color: var(--t2); cursor: pointer; padding: 6px; }
.me-header { display: flex; gap: 12px; align-items: center; padding: 16px; background: var(--surface);
  border-bottom: 1px solid var(--line); }
.who { flex: 1; min-width: 0; }
.name { font-size: 18px; font-weight: 700; display: flex; align-items: center; gap: 6px; }
.tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--accent-soft); color: var(--accent); }
.sub { font-size: var(--fs-cap); color: var(--t4); margin-top: 3px; }
.card { margin: 8px 16px 0; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-md); box-shadow: var(--shadow); }
.quota { padding: 12px; }
.quota header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.quota small { font-size: 10px; color: var(--t4); font-weight: 400; }
.row { margin-bottom: 10px; }
.row:last-child { margin-bottom: 0; }
.lab { display: flex; justify-content: space-between; font-size: var(--fs-cap); color: var(--t3); margin-bottom: 4px; }
.lab b { color: var(--t1); }
.track { height: 5px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
.track i { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
.track i.warn { background: var(--warn-strong); }
.sec { padding: 14px 16px 8px; font-size: var(--fs-md); font-weight: 700; }
.menu { overflow: hidden; }
.mi { display: flex; align-items: center; gap: 10px; padding: 12px; border-bottom: 1px solid var(--line);
  text-decoration: none; color: inherit; }
.mi:last-child { border-bottom: none; }
.ico { width: 28px; height: 28px; border-radius: 8px; background: var(--surface-2); color: var(--t2);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.ico.accent { background: var(--accent-soft); color: var(--accent); }
.ico .app-icon { width: 16px; height: 16px; }
.txt { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.txt b { font-size: var(--fs-md); }
.txt small { font-size: 10px; color: var(--t4); margin-top: 1px; }
.arrow { color: var(--t4); }
.logout { margin: 12px 16px 0; width: calc(100% - 32px); padding: 12px; background: var(--surface);
  border: 1px solid var(--line); border-radius: var(--r-md); color: var(--err); font-size: var(--fs-md);
  font-weight: 600; cursor: pointer; }
.foot { text-align: center; font-size: var(--fs-cap); color: var(--t3); padding: 12px 0 0; }
.pad-bottom { height: 72px; }
</style>
