<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import AuthImage from '../../files/components/AuthImage.vue'
import NavBar from '../../theme/components/NavBar.vue'
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { dmApi, friendsApi, uploadsApi, type DmMessage } from '../../interfaces/api/resources'
import type { UploadResult } from '../../interfaces/api/types'
import { getToken } from '../../interfaces/api/client'
import { DmSocket } from '../../core/composables/dmSocket'
import { useAuthStore } from '../../core/stores/auth'
import { useToastStore } from '../../core/stores/toast'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()
const auth = useAuthStore()
const uid = Number(route.params.userId)
const nickname = ref('私聊')
const msgs = ref<DmMessage[]>([])
const draft = ref('')
const box = ref<HTMLElement | null>(null)
const attach = ref<UploadResult | null>(null)
const uploadPct = ref(0)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
let lastId = 0
let pollTimer: number | undefined

async function down() { await nextTick(); if (box.value) box.value.scrollTop = box.value.scrollHeight }

async function pull(initial = false) {
  try {
    const items = await dmApi.list(uid, initial ? 0 : lastId)
    if (items.length) {
      if (initial) msgs.value = items
      else {
        for (const m of items) if (!msgs.value.some((x) => x.id === m.id)) msgs.value.push(m)
      }
      lastId = msgs.value[msgs.value.length - 1].id
      await down()
    }
    if (initial) await dmApi.markRead(uid)
  } catch (e: any) {
    if (initial) { toast.show(e.message ?? '加载失败', 'error'); await router.push('/friends') }
  }
}

async function load() {
  try {
    const fl = await friendsApi.list()
    const f = fl.find((x) => x.user_id === uid)
    if (!f) { toast.show('你们还不是好友', 'error'); await router.push('/friends'); return }
    nickname.value = f.nickname
  } catch { /* 名称降级 */ }
  await pull(true)
}

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  uploadPct.value = 0
  try { attach.value = await uploadsApi.upload(file, (pct) => { uploadPct.value = pct }) }
  catch (err: any) { toast.show(err.message ?? '上传失败', 'error') }
  finally { uploading.value = false }
}

async function send() {
  const text = draft.value.trim()
  if ((!text && !attach.value) || uploading.value) return
  const att = attach.value
  draft.value = ''
  attach.value = null
  try {
    const d = await dmApi.send(uid, text || '[图片]', att?.id)
    msgs.value.push({ id: d.message_id, sender_id: auth.user?.id ?? 0, recipient_id: uid,
                      content: text || '[图片]', attachment_id: att?.id ?? null,
                      read_at: null, created_at: new Date().toISOString() })
    lastId = d.message_id
    await down()
  } catch (e: any) { toast.show(e.message ?? '发送失败', 'error'); draft.value = text; attach.value = att }
}

function startPolling() {
  window.clearInterval(pollTimer)
  pollTimer = window.setInterval(() => { void pull() }, 3000)
}
function stopPolling() { window.clearInterval(pollTimer); pollTimer = undefined }

const socket = new DmSocket({
  token: getToken,
  onDm: (m) => {
    const msg = m as unknown as DmMessage
    if (msg.sender_id !== uid) return
    if (!msgs.value.some((x) => x.id === msg.id)) {
      msgs.value.push(msg)
      lastId = Math.max(lastId, msg.id)
      void down()
    }
    void dmApi.markRead(uid)
  },
  onEvent: (e) => {
    if (e.type === 'friend_removed' && e.user_id === uid) {
      toast.show('对方已解除好友关系')
      void router.push('/friends')
      return
    }
    if (e.type === 'dm_read' && e.reader_id === uid) {
      for (const m of msgs.value) if (m.sender_id === auth.user?.id) m.read_at = new Date().toISOString()
    }
  },
  onFallback: (active) => { if (active) startPolling(); else { stopPolling(); void pull() } },
})

onMounted(() => { void load(); socket.start() })
onUnmounted(() => { socket.stop(); stopPolling() })
</script>

<template>
  <div class="app-container chat">
    <NavBar :title="nickname" sub="好友私聊 · 端到端实时">
      <template #left>
        <button class="icon-btn" aria-label="返回" @click="router.push('/friends')">
          <AppIcon name="back" />
        </button>
      </template>
    </NavBar>

    <div ref="box" class="body">
      <p v-if="!msgs.length" class="empty">你们已是好友，说点什么吧。</p>
      <div v-for="m in msgs" :key="m.id" class="dm-msg" :class="{ mine: m.sender_id === auth.user?.id }">
        <div class="bubble">
          <AuthImage v-if="m.attachment_id" :upload-id="m.attachment_id" />
          {{ m.content }}
        </div>
        <span v-if="m.sender_id === auth.user?.id" class="read-state">
          {{ m.read_at ? '已读' : '未读' }}
        </span>
      </div>
    </div>

    <div class="composer-wrap">
      <div v-if="attach || uploading" class="attach-chip">
        <AuthImage v-if="attach" :upload-id="attach.id" small />
        <span class="aname">{{ uploading ? `上传中 ${uploadPct}%` : attach?.filename }}</span>
        <button v-if="attach" class="rm" aria-label="移除附件" @click="attach = null">
          <AppIcon name="close" />
        </button>
      </div>
      <div class="composer">
        <button class="icon-btn up" aria-label="上传图片" :disabled="uploading"
                @click="fileInput?.click()">
          <AppIcon name="image" />
        </button>
        <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/gif,image/webp"
               class="hidden-file" @change="onFile" />
        <input v-model="draft" class="input" placeholder="发消息…" @keydown.enter.prevent="send" />
        <button class="send" aria-label="发送" :disabled="(!draft.trim() && !attach) || uploading"
                @click="send">
          <AppIcon name="send" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat { height: 100dvh; }
.icon-btn { background: none; border: none; color: var(--t2); cursor: pointer; padding: 6px; }
.body { flex: 1; min-height: 0; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.empty { text-align: center; color: var(--t4); font-size: var(--fs-sm); padding: 32px 0; }
.dm-msg { display: flex; flex-direction: column; align-items: flex-start; max-width: 86%; }
.dm-msg.mine { align-self: flex-end; align-items: flex-end; }
.bubble { padding: 9px 12px; border-radius: var(--r-md); font-size: var(--fs-md);
  white-space: pre-wrap; word-break: break-word; background: var(--surface);
  border: 1px solid var(--line); border-top-left-radius: 3px; }
.dm-msg.mine .bubble { background: var(--accent); border-color: var(--accent); color: #fff;
  border-top-left-radius: var(--r-md); border-top-right-radius: 3px; }
.read-state { font-size: 10px; color: var(--t4); margin-top: 2px; }
.composer-wrap { flex-shrink: 0; background: var(--surface); border-top: 1px solid var(--line); }
.composer { display: flex; gap: 6px; align-items: center; padding: 8px 12px
  calc(8px + env(safe-area-inset-bottom)); }
.hidden-file { display: none; }
.icon-btn.up { flex-shrink: 0; color: var(--t3); }
.icon-btn.up .app-icon { width: 20px; height: 20px; }
.attach-chip { display: flex; align-items: center; gap: 8px; padding: 6px 12px;
  background: var(--surface-2); border-bottom: 1px solid var(--line); }
.aname { flex: 1; min-width: 0; font-size: var(--fs-cap); color: var(--t2);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rm { background: none; border: none; color: var(--t3); cursor: pointer; padding: 4px; }
.rm .app-icon { width: 14px; height: 14px; }
.input { flex: 1; min-width: 0; padding: 9px 12px; background: var(--surface-2);
  border: 1px solid var(--line); border-radius: 18px; font-size: var(--fs-md);
  color: var(--t1); outline: none; }
.input:focus { border-color: var(--accent); background: var(--surface); }
.send { width: 32px; height: 32px; border-radius: 8px; border: none; background: var(--accent);
  color: #fff; display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
.send:disabled { opacity: .45; cursor: not-allowed; }
.send .app-icon { width: 18px; height: 18px; }
</style>