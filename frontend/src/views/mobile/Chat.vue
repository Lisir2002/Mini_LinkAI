<script setup lang="ts">
import AppIcon from '../../components/common/AppIcon.vue'
import { nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import NavBar from '../../components/common/NavBar.vue'
import Chip from '../../components/common/Chip.vue'
import Drawer from '../../components/common/Drawer.vue'
import ShareExportDrawer from '../../components/common/ShareExportDrawer.vue'
import AuthImage from '../../components/common/AuthImage.vue'
import { conversationsApi, feedbackApi, modelsApi, uploadsApi } from '../../api/resources'
import type { UploadResult } from '../../api/types'
import { streamSSE } from '../../api/sse'
import type { Message, VisibleModel } from '../../api/types'
import { useToastStore } from '../../stores/toast'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()
const cid = Number(route.params.id)
const title = ref('会话')
const modelName = ref('')
const messages = ref<Message[]>([])
const draft = ref('')
const streaming = ref(false)
const streamText = ref('')
const usage = ref<{ prompt_tokens: number; completion_tokens: number; total_tokens: number; estimated?: boolean } | null>(null)
const models = ref<VisibleModel[]>([])
const picking = ref(false)
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
  } catch (err: any) { toast.show(err.message ?? '上传失败', 'error') }
  finally { uploading.value = false }
}
const box = ref<HTMLElement | null>(null)
const quoting = ref<Message | null>(null)
const feedbacks = ref<Record<number, 'up' | 'down' | undefined>>({})
const highlightId = ref<number | null>(null)
let abort: AbortController | null = null
let pressTimer: number | undefined
let hlTimer: number | undefined

function pressStart(m: Message) {
  pressTimer = window.setTimeout(() => { quoting.value = m }, 500)
}
function pressEnd() { window.clearTimeout(pressTimer) }
function jumpTo(id: number) {
  const el = box.value?.querySelector(`[data-mid="${id}"]`)
  if (!el) { toast.show('原消息不在当前列表', 'error'); return }
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  highlightId.value = id
  window.clearTimeout(hlTimer)
  hlTimer = window.setTimeout(() => { highlightId.value = null }, 1500)
}
async function vote(m: Message, rating: 'up' | 'down') {
  const prev = feedbacks.value[m.id]
  feedbacks.value[m.id] = prev === rating ? undefined : rating
  try {
    const state = await feedbackApi.vote(m.id, rating)
    feedbacks.value[m.id] = state === 'none' ? undefined : state
  } catch (e: any) {
    feedbacks.value[m.id] = prev
    toast.show(e.message ?? '反馈失败', 'error')
  }
}

async function scrollDown() { await nextTick(); if (box.value) box.value.scrollTop = box.value.scrollHeight }
async function load() {
  try {
    const [cs, ms] = await Promise.all([conversationsApi.list(), modelsApi.visible()])
    const c = cs.find((x) => x.id === cid)
    if (!c) { toast.show('会话不存在', 'error'); await router.push('/msgs'); return }
    title.value = c.title
    models.value = ms
    const all = await modelsApi.list().catch(() => [])
    modelName.value = all.find((m) => m.id === c.model_id)?.public_name ?? '未绑定模型'
    messages.value = await conversationsApi.messages(cid)
    await scrollDown()
    const target = Number(route.query.msg)
    if (target) jumpTo(target)
  } catch (e: any) { toast.show(e.message ?? '加载失败', 'error') }
}
async function pick(name: string) {
  const all = await modelsApi.list().catch(() => [])
  const m = all.find((x) => x.public_name === name)
  if (!m) return
  await conversationsApi.patch(cid, { model_id: m.id })
  modelName.value = name
  picking.value = false
  toast.show(`已切换为 ${name}，新消息生效`, 'success')
}
function stop() { abort?.abort(); streaming.value = false; toast.show('已停止生成') }
async function send() {
  const text = draft.value.trim()
  if (!text || streaming.value) return
  const q = quoting.value
  const att = attach.value
  draft.value = ''
  quoting.value = null
  attach.value = null
  messages.value.push({ id: Date.now(), role: 'user', content: text, status: 'ok',
                        total_tokens: null, created_at: new Date().toISOString(),
                        reply_to_msg_id: q?.id ?? null, attachment_id: att?.id ?? null,
                        quote: q ? { id: q.id, nickname: q.role === 'assistant' ? 'AI' : '我',
                                     excerpt: q.content.slice(0, 80) } : null })
  await scrollDown()
  streaming.value = true
  streamText.value = ''
  usage.value = null
  abort = new AbortController()
  let failed = ''
  await streamSSE(`/api/conversations/${cid}/ai/completions`,
    { content: text, ...(q ? { reply_to_msg_id: q.id } : {}),
      ...(att ? { attachment_id: att.id } : {}) }, (e) => {
    if (e.event === 'delta') { streamText.value += e.data.content; void scrollDown() }
    else if (e.event === 'usage') usage.value = e.data as never
    else if (e.event === 'error') failed = e.data.message ?? '生成失败'
  }, abort.signal)
  streaming.value = false
  abort = null
  if (failed) { toast.show(failed, 'error'); streamText.value = '' }
  messages.value = await conversationsApi.messages(cid)
  await scrollDown()
}
async function copy(t: string) {
  try { await navigator.clipboard.writeText(t); toast.show('已复制', 'success') }
  catch { toast.show('复制失败，请手动选择', 'error') }
}
onMounted(load)
</script>

<template>
  <div class="app-container chat">
    <NavBar :title="title" :sub="modelName">
      <template #left>
        <button class="icon-btn" aria-label="返回" @click="router.push('/msgs')">
          <AppIcon name="back" />
        </button>
      </template>
      <template #right>
        <Chip icon="bolt" tone="accent" @click="picking = true">{{ modelName }}</Chip>
        <button class="icon-btn" aria-label="导出与分享" @click="sharing = true">
          <AppIcon name="more" />
        </button>
      </template>
    </NavBar>

    <div ref="box" class="body">
      <p v-if="!messages.length && !streaming" class="empty">发一条消息，开始这段对话。</p>
      <div v-for="m in messages" :key="m.id" class="msg" :class="[m.role, { hl: highlightId === m.id }]"
           :data-mid="m.id">
        <div class="ava"><AppIcon :name="m.role === 'user' ? 'user' : 'robot'" /></div>
        <div class="stack">
          <div class="bubble" @contextmenu.prevent="quoting = m"
               @pointerdown="pressStart(m)" @pointerup="pressEnd" @pointerleave="pressEnd">
            <button v-if="m.quote" class="qblock" @click.stop="jumpTo(m.quote.id)">
              <AppIcon name="quote" />
              <span v-if="m.quote.deleted" class="qdel">原消息已删除</span>
              <span v-else class="qtxt"><b>{{ m.quote.nickname }}</b>{{ m.quote.excerpt }}</span>
            </button>
            <AuthImage v-if="m.attachment_id" :upload-id="m.attachment_id" />
            {{ m.content }}
          </div>
          <div class="meta">
            <span v-if="m.total_tokens">{{ m.total_tokens }} tokens</span>
            <button class="act" @click="quoting = m"><AppIcon name="reply-arrow" />引用</button>
            <button v-if="m.role === 'assistant'" class="act" @click="copy(m.content)">
              <AppIcon name="copy" />复制
            </button>
            <button v-if="m.role === 'assistant'" class="act fb" :class="{ on: feedbacks[m.id] === 'up' }"
                    aria-label="有帮助" @click="vote(m, 'up')"><AppIcon name="thumbs-up" /></button>
            <button v-if="m.role === 'assistant'" class="act fb" :class="{ on: feedbacks[m.id] === 'down' }"
                    aria-label="没帮助" @click="vote(m, 'down')"><AppIcon name="thumbs-down" /></button>
          </div>
        </div>
      </div>
      <div v-if="streaming" class="msg assistant">
        <div class="ava"><AppIcon name="robot" /></div>
        <div class="stack">
          <div class="bubble">
            <template v-if="streamText">{{ streamText }}</template>
            <span v-else class="dots"><i /><i /><i /></span>
          </div>
          <div class="meta">{{ modelName }} · 生成中…</div>
        </div>
      </div>
      <p v-if="usage" class="usage">
        本次 {{ usage.total_tokens }} tokens（输入 {{ usage.prompt_tokens }} / 输出 {{ usage.completion_tokens }}）
        <b v-if="usage.estimated">· 用量为本地估算</b>
      </p>
    </div>

    <div class="composer-wrap">
      <div v-if="quoting" class="qbar">
        <AppIcon name="quote" />
        <span class="qbar-txt">回复 {{ quoting.role === 'assistant' ? 'AI' : '我' }}：{{ quoting.content.slice(0, 60) }}</span>
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
      <input v-model="draft" class="input" placeholder="输入消息，Enter 发送…"
             @keydown.enter.prevent="send" />
      <button v-if="streaming" class="send stop" aria-label="停止" @click="stop">
        <AppIcon name="stop" />
      </button>
      <button v-else class="send" aria-label="发送" :disabled="!draft.trim()" @click="send">
        <AppIcon name="send" />
      </button>
      </div>
    </div>

    <ShareExportDrawer :open="sharing" scope="dm" :target-id="cid" :title="title"
                       @close="sharing = false" />

    <Drawer :open="picking" title="切换模型" desc="切换后新消息使用新模型，历史不串" @close="picking = false">
      <button v-for="m in models" :key="m.public_name" class="mopt"
              :class="{ on: m.public_name === modelName }" @click="pick(m.public_name)">
        <span class="mi"><AppIcon name="bolt" /></span>
        <span class="mt"><b>{{ m.display_name }}</b>
          <small>{{ m.public_name }} · {{ Math.round(m.context_limit / 1024) }}k 上下文</small></span>
        <AppIcon name="check" class="chk" v-if="m.public_name === modelName" />
      </button>
      <p v-if="!models.length" class="none">暂无可用模型，请联系管理员配置渠道。</p>
    </Drawer>
  </div>
</template>

<style scoped>
.chat { height: 100dvh; }
.icon-btn { background: none; border: none; color: var(--t2); cursor: pointer; padding: 6px; }
.body { flex: 1; min-height: 0; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 12px; }
.empty { text-align: center; color: var(--t4); font-size: var(--fs-sm); padding: 32px 0; }
.msg { display: flex; gap: 8px; max-width: 92%; }
.msg.user { align-self: flex-end; flex-direction: row-reverse; }
.msg.assistant { align-self: flex-start; }
.ava { width: 26px; height: 26px; border-radius: 7px; flex-shrink: 0; display: flex;
  align-items: center; justify-content: center; background: var(--t1); color: var(--accent); }
.msg.user .ava { background: var(--accent); color: #fff; }
.ava .app-icon { width: 15px; height: 15px; }
.stack { min-width: 0; }
.bubble { padding: 9px 12px; border-radius: var(--r-md); font-size: var(--fs-md); white-space: pre-wrap;
  word-break: break-word; background: var(--surface); border: 1px solid var(--line); border-top-left-radius: 3px; }
.msg.user .bubble { background: var(--accent); border-color: var(--accent); color: #fff;
  border-top-left-radius: var(--r-md); border-top-right-radius: 3px; }
.msg.assistant .bubble { position: relative; padding-left: 15px; }
.msg.assistant .bubble::before { content: ''; position: absolute; left: 6px; top: 8px; bottom: 8px;
  width: 2px; border-radius: 1px; background: var(--accent); }
.meta { font-size: 10px; color: var(--t3); margin-top: 3px; display: flex; gap: 8px; align-items: center; }
.msg.user .meta { justify-content: flex-end; }
.act { display: inline-flex; align-items: center; gap: 2px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 4px; padding: 2px 6px; color: var(--t3);
  font-size: 10px; cursor: pointer; }
.act .app-icon { width: 12px; height: 12px; }
.dots i { display: inline-block; width: 5px; height: 5px; border-radius: 50%; background: var(--t4);
  margin-right: 3px; animation: blink 1s infinite; }
.dots i:nth-child(2) { animation-delay: .2s; }
.dots i:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%,100% { opacity: .3 } 50% { opacity: 1 } }
.usage { align-self: center; font-size: 10px; color: var(--t4); background: var(--surface-2);
  padding: 3px 10px; border-radius: 10px; }
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
.qbar { display: flex; align-items: center; gap: 6px; padding: 6px 12px; font-size: var(--fs-sm);
  color: var(--t2); background: var(--accent-soft); border-bottom: 1px solid var(--line); }
.qbar .app-icon { width: 14px; height: 14px; color: var(--accent); flex-shrink: 0; }
.qbar-txt { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qcancel { background: none; border: none; color: var(--t3); cursor: pointer; padding: 4px; }
.qcancel .app-icon { width: 14px; height: 14px; }
.qblock { display: flex; align-items: flex-start; gap: 5px; width: 100%; text-align: left;
  background: var(--surface-2); border: none; border-left: 2px solid var(--accent);
  border-radius: 6px; padding: 5px 8px; margin-bottom: 6px; cursor: pointer;
  font-size: var(--fs-sm); color: var(--t2); }
.msg.user .qblock { background: rgba(255,255,255,.16); color: #fff; border-left-color: #fff; }
.qblock .app-icon { width: 13px; height: 13px; flex-shrink: 0; margin-top: 2px; }
.qtxt { min-width: 0; overflow: hidden; text-overflow: ellipsis; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.qtxt b { margin-right: 5px; }
.qdel { color: var(--t4); font-style: italic; }
.msg.user .qdel { color: rgba(255,255,255,.7); }
.act.fb.on { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
.msg.hl .bubble { animation: hlflash 1.5s ease-out; }
@keyframes hlflash { 0% { box-shadow: 0 0 0 3px var(--accent); } 100% { box-shadow: 0 0 0 0 transparent; } }
.input { flex: 1; min-width: 0; padding: 9px 12px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 18px; font-size: var(--fs-md); color: var(--t1); outline: none; }
.input:focus { border-color: var(--accent); background: var(--surface); }
.send { width: 32px; height: 32px; border-radius: 8px; border: none; background: var(--accent); color: #fff;
  display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
.send:disabled { opacity: .45; cursor: not-allowed; }
.send.stop { background: var(--err); }
.send .app-icon { width: 18px; height: 18px; }
.mopt { width: 100%; display: flex; align-items: center; gap: 10px; padding: 10px; margin-bottom: 8px;
  border: 1px solid var(--line); border-radius: var(--r-md); background: var(--surface); cursor: pointer; text-align: left; }
.mopt.on { border-color: var(--accent); background: var(--accent-soft); }
.mi { width: 30px; height: 30px; border-radius: 8px; background: var(--t1); color: var(--accent);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.mt { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.mt b { font-size: var(--fs-md); }
.mt small { font-size: 10px; color: var(--t3); margin-top: 2px; }
.chk { color: var(--accent); }
.none { font-size: var(--fs-sm); color: var(--t3); padding: 12px 0; }
</style>
