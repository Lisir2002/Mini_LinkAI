<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { request } from '../../interfaces/api/client'

interface SharedMessage { role: string; content: string; nickname: string | null; created_at: string }
const route = useRoute()
const title = ref('')
const expires = ref('')
const messages = ref<SharedMessage[]>([])
const error = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const d = await request<{ title: string; expires_at: string; messages: SharedMessage[] }>(
      `/api/share/${route.params.token}`)
    title.value = d.data.title
    expires.value = new Date(d.data.expires_at).toLocaleString()
    messages.value = d.data.messages
  } catch (e: any) {
    error.value = e.code === 'SHARE_EXPIRED' ? '分享已过期'
      : e.code === 'SHARE_REVOKED' ? '分享已被撤销'
      : e.code === 'SHARE_TAMPERED' ? '分享链接无效'
      : (e.message ?? '加载失败')
  } finally { loading.value = false }
})

function who(m: SharedMessage) {
  return m.nickname ?? (m.role === 'assistant' ? 'AI' : m.role === 'system' ? '系统' : '成员')
}
</script>

<template>
  <div class="share-page">
    <header class="head">
      <AppIcon name="brand-chat" />
      <div class="ht">
        <b>{{ title || '只读分享' }}</b>
        <small v-if="expires">有效期至 {{ expires }} · 只读，无法回复</small>
      </div>
    </header>
    <p v-if="loading" class="state">加载中…</p>
    <div v-else-if="error" class="state err">
      <AppIcon name="warning" /><b>{{ error }}</b>
      <span>请联系分享者重新生成链接</span>
    </div>
    <main v-else class="body">
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <span class="who">{{ who(m) }}</span>
        <p class="content">{{ m.content }}</p>
      </div>
      <p v-if="!messages.length" class="state">暂无消息</p>
    </main>
    <footer class="foot">由 AI 聊天室生成 · 内容仅代表分享者会话记录</footer>
  </div>
</template>

<style scoped>
.share-page { max-width: 640px; margin: 0 auto; min-height: 100dvh; display: flex; flex-direction: column; }
.head { display: flex; gap: 10px; align-items: center; padding: 16px; border-bottom: 1px solid var(--line);
  background: var(--surface); position: sticky; top: 0; }
.head .app-icon { width: 28px; height: 28px; color: var(--accent); }
.ht { display: flex; flex-direction: column; min-width: 0; }
.ht b { font-size: var(--fs-lg); }
.ht small { font-size: var(--fs-cap); color: var(--t3); }
.state { padding: 40px 16px; text-align: center; color: var(--t4); display: flex; flex-direction: column;
  align-items: center; gap: 8px; }
.state.err { color: var(--err); }
.state .app-icon { width: 32px; height: 32px; }
.body { flex: 1; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.msg { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); padding: 10px 12px; }
.msg.assistant { border-left: 3px solid var(--accent); }
.msg.system { background: var(--surface-2); font-size: var(--fs-cap); color: var(--t3); }
.who { font-size: var(--fs-cap); font-weight: 700; color: var(--t3); }
.msg.assistant .who { color: var(--accent); }
.content { margin: 4px 0 0; white-space: pre-wrap; word-break: break-word; font-size: var(--fs-md); }
.foot { padding: 14px 16px calc(14px + env(safe-area-inset-bottom)); text-align: center;
  font-size: var(--fs-cap); color: var(--t4); border-top: 1px solid var(--line); }
</style>