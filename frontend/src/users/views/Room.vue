<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import NavBar from '../../theme/components/NavBar.vue'
import ShareExportDrawer from '../../files/components/ShareExportDrawer.vue'
import ConfirmDialog from '../../theme/components/ConfirmDialog.vue'
import StructuredView from '../../llm/components/StructuredView.vue'
import AuthImage from '../../files/components/AuthImage.vue'
import Drawer from '../../theme/components/Drawer.vue'
import { roomsApi, templatesApi, type RoomMessage } from '../../interfaces/api/rooms'
import { feedbackApi, uploadsApi } from '../../interfaces/api/resources'
import type { UploadResult } from '../../interfaces/api/types'
import { getToken } from '../../interfaces/api/client'
import { RoomSocket } from '../../core/composables/roomSocket'
import { streamSSE } from '../../interfaces/api/sse'
import { ApiError } from '../../interfaces/api/client'
import { useAuthStore } from '../../core/stores/auth'
import { useToastStore } from '../../core/stores/toast'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()
const auth = useAuthStore()
const rid = Number(route.params.id)
const name = ref('房间')
const modelName = ref('')
const aiStatus = ref('normal')
const ownerId = ref<number | null>(null)
const publishing = ref(false)
const settings = ref(false)
const setMode = ref('free')
const setSchema = ref('')
const saving = ref(false)

async function saveSettings() {
  saving.value = true
  try {
    const body: Record<string, unknown> = { output_mode: setMode.value }
    if (setMode.value === 'json' && setSchema.value.trim()) body.output_schema = setSchema.value.trim()
    await roomsApi.patch(rid, body)
    toast.show('输出模式已保存，新回复生效', 'success')
    settings.value = false
  } catch (e) { toast.show((e as ApiError).message, 'error') }
  finally { saving.value = false }
}
const isOwner = computed(() => ownerId.value !== null && ownerId.value === auth.user?.id)
const msgs = ref<RoomMessage[]>([])
const draft = ref('')
const streaming = ref(false)
const streamText = ref('')
const box = ref<HTMLElement | null>(null)
let timer: number | undefined
let lastId = 0
const online = ref(0)
const sharing = ref(false)
const attach = ref<UploadResult | null>(null)
const uploadPct = ref(0)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  uploadPct.value = 0
  try {
    attach.value = await uploadsApi.upload(file, (pct) => { uploadPct.value = pct })
  } catch (err) { toast.show((err as Error).message ?? '上传失败', 'error') }
  finally { uploading.value = false }
}
const fallback = ref(false)

function startPolling() {
  window.clearInterval(timer)
  timer = window.setInterval(() => { if (!streaming.value) void pull() }, 3000)
}
function stopPolling() { window.clearInterval(timer); timer = undefined }

const socket = new RoomSocket({
  rid,
  token: getToken,
  onMessage: (m) => {
    const id = Number(m.id)
    if (!id || id <= lastId || msgs.value.some((x) => x.id === id)) return
    msgs.value.push(m as unknown as RoomMessage)
    lastId = id
    void down()
  },
  onOnline: (n) => { online.value = n },
  onFallback: (active) => {
    fallback.value = active
    if (active) startPolling()
    else { stopPolling(); void pull() }
  },
})
const quoting = ref<RoomMessage | null>(null)
const feedbacks = ref<Record<number, 'up' | 'down' | undefined>>({})
const highlightId = ref<number | null>(null)
let pressTimer: number | undefined
let hlTimer: number | undefined

function pressStart(m: RoomMessage) { pressTimer = window.setTimeout(() => { quoting.value = m }, 500) }
function pressEnd() { window.clearTimeout(pressTimer) }
function jumpTo(id: number) {
  const el = box.value?.querySelector(`[data-mid="${id}"]`)
  if (!el) { toast.show('原消息不在当前列表', 'error'); return }
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  highlightId.value = id
  window.clearTimeout(hlTimer)
  hlTimer = window.setTimeout(() => { highlightId.value = null }, 1500)
}
async function vote(m: RoomMessage, rating: 'up' | 'down') {
  const prev = feedbacks.value[m.id]
  feedbacks.value[m.id] = prev === rating ? undefined : rating
  try {
    const state = await feedbackApi.vote(m.id, rating)
    feedbacks.value[m.id] = state === 'none' ? undefined : state
  } catch (e) {
    feedbacks.value[m.id] = prev
    toast.show((e as ApiError).message ?? '反馈失败', 'error')
  }
}

async function down() { await nextTick(); if (box.value) box.value.scrollTop = box.value.scrollHeight }
async function pull(initial = false) {
  try {
    const d = await roomsApi.messages(rid, initial ? 0 : lastId)
    name.value = d.room.name
    modelName.value = d.room.model_name ?? '未绑定模型'
    aiStatus.value = d.room.ai_status
    ownerId.value = d.room.owner_id ?? null
    if (d.items.length) {
      if (initial) msgs.value = d.items
      else msgs.value.push(...d.items)
      lastId = msgs.value[msgs.value.length - 1].id
      await down()
    }
  } catch (e) {
    if (initial) { toast.show((e as ApiError).message, 'error'); await router.push('/rooms') }
  }
}
async function send(useAI: boolean) {
  const text = draft.value.trim()
  if (!text || streaming.value) return
  const q = quoting.value
  const att = attach.value
  draft.value = ''
  quoting.value = null
  attach.value = null
  if (!useAI) {
    try { await roomsApi.send(rid, text, q?.id, att?.id); if (fallback.value) await pull() }
    catch (e) { toast.show((e as ApiError).message, 'error'); draft.value = text; quoting.value = q; attach.value = att }
    return
  }
  streaming.value = true
  streamText.value = ''
  let failed = ''
  await streamSSE(`/api/rooms/${rid}/ai/ask`,
    { content: text, ...(q ? { reply_to_msg_id: q.id } : {}),
      ...(att ? { attachment_id: att.id } : {}) }, (e) => {
    if (e.event === 'delta') { streamText.value += e.data.content; void down() }
    else if (e.event === 'error') failed = e.data.message ?? '生成失败'
  })
  streaming.value = false
  streamText.value = ''
  if (failed) toast.show(failed, 'error')
  if (fallback.value) await pull()
}
async function leave() {
  try { await roomsApi.leave(rid); toast.show('已退出房间'); await router.push('/rooms') }
  catch (e) { toast.show((e as ApiError).message, 'error') }
}
function insertAI() { if (!draft.value.includes('@AI')) draft.value = `@AI ${draft.value}`.trim() }
async function publishTemplate() {
  publishing.value = false
  try {
    await templatesApi.publish(rid)
    toast.show('已发布到模板市场', 'success')
  } catch (e) { toast.show((e as ApiError).message, 'error') }
}
onMounted(async () => {
  await pull(true)
  const target = Number(route.query.msg)
  if (target) jumpTo(target)
  socket.start()
})
onUnmounted(() => { socket.stop(); stopPolling() })
</script>

<template>
  <div class="app-container chat">
    <NavBar :title="name" :sub="`${modelName} · AI ${aiStatus} · ${online} 人在线`">
      <template #left>
        <button class="icon-btn" aria-label="返回" @click="router.push('/rooms')">
          <AppIcon name="back" />
        </button>
      </template>
      <template #right>
        <button v-if="isOwner" class="icon-btn" aria-label="房间设置" @click="settings = true">
          <AppIcon name="gear" />
        </button>
        <button class="icon-btn" aria-label="导出与分享" @click="sharing = true">
          <AppIcon name="more" />
        </button>
        <button class="icon-btn" aria-label="退出房间" @click="leave">
          <AppIcon name="logout" />
        </button>
      </template>
    </NavBar>
    <p class="topic">房间消息对所有成员可见；点「@AI」才会调用模型，用量计入房主配额。
      <button v-if="isOwner" class="pub" @click="publishing = true">
        <AppIcon name="grid" />发布为模板
      </button>
    </p>

    <div ref="box" class="body">
      <p v-if="!msgs.length" class="empty">还没有消息，说点什么吧。</p>
      <template v-for="m in msgs" :key="m.id">
        <p v-if="m.role === 'system'" class="sys">{{ m.content }}</p>
        <div v-else class="msg" :class="{ mine: m.role === 'user' && m.nickname === auth.user?.nickname,
                                        ai: m.role === 'assistant', hl: highlightId === m.id }"
             :data-mid="m.id">
          <div class="ava"><AppIcon :name="m.role === 'assistant' ? 'robot' : 'user'" /></div>
          <div class="stack">
            <div v-if="m.role !== 'assistant'" class="who">{{ m.nickname ?? '成员' }}</div>
            <div v-else class="who ai-tag">AI · {{ modelName }}</div>
            <div class="bubble" @contextmenu.prevent="quoting = m"
                 @pointerdown="pressStart(m)" @pointerup="pressEnd" @pointerleave="pressEnd">
              <button v-if="m.quote" class="qblock" @click.stop="jumpTo(m.quote.id)">
                <AppIcon name="quote" />
                <span v-if="m.quote.deleted" class="qdel">原消息已删除</span>
                <span v-else class="qtxt"><b>{{ m.quote.nickname }}</b>{{ m.quote.excerpt }}</span>
              </button>
              <AuthImage v-if="m.attachment_id" :upload-id="m.attachment_id" />
              <StructuredView v-if="m.role === 'assistant' && m.output_mode && m.output_mode !== 'free'"
                              :mode="m.output_mode" :content="m.content" />
              <template v-else>{{ m.content }}</template>
            </div>
            <div class="meta">
              <span v-if="m.output_downgraded" class="downgraded">输出未通过 JSON 校验，已降级为纯文本</span>
              <span v-if="m.total_tokens">{{ m.total_tokens }} tokens · 计入房主配额</span>
              <button class="act" @click="quoting = m"><AppIcon name="reply-arrow" />引用</button>
              <button v-if="m.role === 'assistant'" class="act fb" :class="{ on: feedbacks[m.id] === 'up' }"
                      aria-label="有帮助" @click="vote(m, 'up')"><AppIcon name="thumbs-up" /></button>
              <button v-if="m.role === 'assistant'" class="act fb" :class="{ on: feedbacks[m.id] === 'down' }"
                      aria-label="没帮助" @click="vote(m, 'down')"><AppIcon name="thumbs-down" /></button>
            </div>
          </div>
        </div>
      </template>
      <div v-if="streaming" class="msg ai">
        <div class="ava"><AppIcon name="robot" /></div>
        <div class="stack">
          <div class="who ai-tag">AI · 生成中…</div>
          <div class="bubble">
            <template v-if="streamText">{{ streamText }}</template>
            <span v-else class="dots"><i /><i /><i /></span>
          </div>
        </div>
      </div>
    </div>

    <div class="composer-wrap">
      <div v-if="quoting" class="qbar">
        <AppIcon name="quote" />
        <span class="qbar-txt">回复 {{ quoting.nickname ?? '成员' }}：{{ quoting.content.slice(0, 60) }}</span>
        <button class="qcancel" aria-label="取消引用" @click="quoting = null"><AppIcon name="close" /></button>
      </div>
      <div v-if="attach || uploading" class="attach-chip">
        <AuthImage v-if="attach" :upload-id="attach.id" small />
        <span class="aname">{{ uploading ? `上传中 ${uploadPct}%` : attach?.filename }}</span>
        <button v-if="attach" class="qcancel" aria-label="移除附件" @click="attach = null">
          <AppIcon name="close" />
        </button>
      </div>
      <div class="composer">
      <button class="icon-btn up" aria-label="上传图片" :disabled="uploading"
              @click="fileInput?.click()">
        <AppIcon name="image" />
      </button>
      <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf"
             class="hidden-file" @change="onFile" />
      <button class="at" :disabled="aiStatus !== 'normal'" @click="insertAI">@AI</button>
      <input v-model="draft" class="input" placeholder="发消息，@AI 触发模型…"
             @keydown.enter.prevent="send(draft.includes('@AI'))" />
      <button class="send" :disabled="!draft.trim() || streaming"
              @click="send(draft.includes('@AI'))">
        <AppIcon name="send" />
      </button>
      </div>
    </div>
    <ShareExportDrawer :open="sharing" scope="room" :target-id="rid" :title="name"
                       @close="sharing = false" />
    <Drawer :open="settings" title="房间设置" desc="结构化输出约束只对新的 AI 回复生效"
            @close="settings = false">
      <label class="fl">输出模式</label>
      <select v-model="setMode" class="fi">
        <option value="free">自由文本</option>
        <option value="json">JSON 对象</option>
        <option value="table">Markdown 表格</option>
        <option value="code">代码块</option>
      </select>
      <template v-if="setMode === 'json'">
        <label class="fl">JSON Schema（可选）</label>
        <textarea v-model="setSchema" class="fi ta" rows="4"
                  placeholder='{"type":"object","required":["answer"]}'></textarea>
        <p class="tip">校验失败自动重试一次，再失败降级为纯文本并标注。</p>
      </template>
      <template #footer>
        <button class="primary" :disabled="saving" @click="saveSettings">
          {{ saving ? '保存中…' : '保存设置' }}
        </button>
      </template>
    </Drawer>

    <ConfirmDialog :open="publishing" title="发布为模板"
                   message="将把本房间的名称、简介、提示词、模型与准入配置发布到模板市场，其他成员可一键克隆开房。私密房间不可发布。"
                   @close="publishing = false" @confirm="publishTemplate" />
  </div>
</template>

<style scoped>
.chat { height: 100dvh; }
.icon-btn { background: none; border: none; color: var(--t2); cursor: pointer; padding: 6px; }
.topic { margin: 8px 12px 0; padding: 7px 10px; background: var(--accent-soft); border-radius: var(--r-md);
  font-size: var(--fs-cap); color: var(--t2); line-height: 1.5; }
.pub { display: inline-flex; align-items: center; gap: 4px; margin-left: 6px; padding: 3px 9px;
  border: 1px solid var(--accent); border-radius: 12px; background: var(--surface);
  color: var(--accent); font-size: var(--fs-cap); font-weight: 700; cursor: pointer; }
.pub .app-icon { width: 12px; height: 12px; }
.downgraded { color: var(--warn, #d97706); font-size: 10px; }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 12px 0 6px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.ta { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; resize: vertical; }
.tip { font-size: var(--fs-cap); color: var(--t4); margin-top: 6px; line-height: 1.5; }
.primary { width: 100%; padding: 12px 0; border: none; border-radius: var(--r-sm); background: var(--accent);
  color: #fff; font-size: var(--fs-lg); font-weight: 600; cursor: pointer; }
.primary:disabled { opacity: .5; }
.body { flex: 1; min-height: 0; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 11px; }
.empty { text-align: center; color: var(--t4); font-size: var(--fs-sm); padding: 28px 0; }
.sys { align-self: center; font-size: 10px; color: var(--t4); background: var(--surface-2);
  padding: 3px 10px; border-radius: 10px; }
.msg { display: flex; gap: 8px; max-width: 92%; align-self: flex-start; }
.msg.mine { align-self: flex-end; flex-direction: row-reverse; }
.ava { width: 26px; height: 26px; border-radius: 7px; flex-shrink: 0; display: flex; align-items: center;
  justify-content: center; background: var(--fill); color: var(--t2); }
.msg.ai .ava { background: var(--t1); color: var(--accent); }
.msg.mine .ava { background: var(--accent); color: #fff; }
.ava .app-icon { width: 15px; height: 15px; }
.stack { min-width: 0; }
.who { font-size: 10px; color: var(--t3); margin-bottom: 3px; }
.ai-tag { color: var(--accent); font-weight: 600; }
.bubble { padding: 9px 12px; border-radius: var(--r-md); font-size: var(--fs-md); white-space: pre-wrap;
  word-break: break-word; background: var(--surface); border: 1px solid var(--line); border-top-left-radius: 3px; }
.msg.mine .bubble { background: var(--accent); border-color: var(--accent); color: #fff;
  border-top-left-radius: var(--r-md); border-top-right-radius: 3px; }
.msg.ai .bubble { border-left: 2px solid var(--accent); }
.meta { font-size: 10px; color: var(--t4); margin-top: 3px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.act { display: inline-flex; align-items: center; gap: 2px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 4px; padding: 2px 6px; color: var(--t3);
  font-size: 10px; cursor: pointer; }
.act .app-icon { width: 12px; height: 12px; }
.act.fb.on { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
.qblock { display: flex; align-items: flex-start; gap: 5px; width: 100%; text-align: left;
  background: var(--surface-2); border: none; border-left: 2px solid var(--accent);
  border-radius: 6px; padding: 5px 8px; margin-bottom: 6px; cursor: pointer;
  font-size: var(--fs-sm); color: var(--t2); }
.msg.mine .qblock { background: rgba(255,255,255,.16); color: #fff; border-left-color: #fff; }
.qblock .app-icon { width: 13px; height: 13px; flex-shrink: 0; margin-top: 2px; }
.qtxt { min-width: 0; overflow: hidden; text-overflow: ellipsis; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.qtxt b { margin-right: 5px; }
.qdel { color: var(--t4); font-style: italic; }
.msg.hl .bubble { animation: hlflash 1.5s ease-out; }
@keyframes hlflash { 0% { box-shadow: 0 0 0 3px var(--accent); } 100% { box-shadow: 0 0 0 0 transparent; } }
.dots i { display: inline-block; width: 5px; height: 5px; border-radius: 50%; background: var(--t4);
  margin-right: 3px; animation: blink 1s infinite; }
.dots i:nth-child(2) { animation-delay: .2s; }
.dots i:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%,100% { opacity: .3 } 50% { opacity: 1 } }
.composer-wrap { flex-shrink: 0; background: var(--surface); border-top: 1px solid var(--line); }
.composer { display: flex; gap: 6px; align-items: center; padding: 8px 12px
  calc(8px + env(safe-area-inset-bottom)); }
.hidden-file { display: none; }
.icon-btn.up { flex-shrink: 0; color: var(--t3); background: none; border: none; cursor: pointer; padding: 6px; }
.icon-btn.up .app-icon { width: 20px; height: 20px; }
.attach-chip { display: flex; align-items: center; gap: 8px; padding: 6px 12px;
  background: var(--surface-2); border-bottom: 1px solid var(--line); }
.aname { flex: 1; min-width: 0; font-size: var(--fs-cap); color: var(--t2);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qbar { display: flex; align-items: center; gap: 6px; padding: 6px 12px; font-size: var(--fs-sm);
  color: var(--t2); background: var(--accent-soft); border-bottom: 1px solid var(--line); }
.qbar .app-icon { width: 14px; height: 14px; color: var(--accent); flex-shrink: 0; }
.qbar-txt { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qcancel { background: none; border: none; color: var(--t3); cursor: pointer; padding: 4px; }
.qcancel .app-icon { width: 14px; height: 14px; }
.at { padding: 7px 9px; border-radius: 8px; border: 1px solid var(--line-2); background: var(--surface-2);
  color: var(--accent); font-size: var(--fs-cap); font-weight: 700; cursor: pointer; flex-shrink: 0; }
.at:disabled { opacity: .45; cursor: not-allowed; }
.input { flex: 1; min-width: 0; padding: 9px 12px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 18px; font-size: var(--fs-md); color: var(--t1); outline: none; }
.send { width: 32px; height: 32px; border-radius: 8px; border: none; background: var(--accent); color: #fff;
  display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
.send:disabled { opacity: .45; cursor: not-allowed; }
.send .app-icon { width: 18px; height: 18px; }
</style>
