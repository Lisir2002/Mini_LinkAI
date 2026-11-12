<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import NavBar from '../../theme/components/NavBar.vue'
import TabBar from '../../theme/components/TabBar.vue'
import Avatar from '../../theme/components/Avatar.vue'
import Drawer from '../../theme/components/Drawer.vue'
import EmptyState from '../../theme/components/EmptyState.vue'
import { conversationsApi, modelsApi, searchApi } from '../../interfaces/api/resources'
import type { Conversation, SearchResult, VisibleModel } from '../../interfaces/api/types'
import { useToastStore } from '../../core/stores/toast'

const router = useRouter()
const toast = useToastStore()
const items = ref<Conversation[]>([])
const models = ref<VisibleModel[]>([])
const q = ref('')
const loading = ref(true)
const creating = ref(false)
const newTitle = ref('')
const newModel = ref('')
let undoTimer: number | undefined
const undone = ref<{ conv: Conversation; index: number } | null>(null)

const filtered = computed(() => {
  const k = q.value.trim().toLowerCase()
  const base = k ? items.value.filter((c) => c.title.toLowerCase().includes(k)) : items.value
  return [...base].sort((a, b) => Number(b.pinned) - Number(a.pinned))
})

async function load() {
  loading.value = true
  try {
    const [cs, ms] = await Promise.all([conversationsApi.list(), modelsApi.visible()])
    items.value = cs
    models.value = ms
    if (!newModel.value && ms.length) newModel.value = ms.find((m) => m.is_default)?.public_name ?? ms[0].public_name
  } catch (e: any) { toast.show(e.message ?? '加载失败', 'error') }
  finally { loading.value = false }
}
async function create() {
  if (!newModel.value) { toast.show('请先在管理端配置并绑定一个可用模型', 'error'); return }
  const m = models.value.find((x) => x.public_name === newModel.value)
  try {
    const c = await conversationsApi.create({
      title: newTitle.value.trim() || '新会话',
      model_id: (await modelsApi.list()).find((x) => x.public_name === m?.public_name)?.id,
    })
    creating.value = false
    newTitle.value = ''
    await router.push(`/c/${c.id}`)
  } catch (e: any) { toast.show(e.message ?? '创建失败', 'error') }
}
async function remove(c: Conversation) {
  const index = items.value.findIndex((x) => x.id === c.id)
  items.value.splice(index, 1)                 // 乐观删除
  undone.value = { conv: c, index }
  try { await conversationsApi.remove(c.id) } catch { /* 已本地移除 */ }
  toast.show('会话已删除，点撤销可恢复')
  window.clearTimeout(undoTimer)
  undoTimer = window.setTimeout(() => { undone.value = null }, 6000)
}
async function undo() {
  if (!undone.value) return
  const { conv } = undone.value
  try {
    const c = await conversationsApi.create({ title: conv.title, model_id: conv.model_id })
    items.value.unshift({ ...conv, id: c.id })
    toast.show('已恢复会话（历史消息随原会话删除）', 'success')
  } catch (e: any) { toast.show(e.message ?? '恢复失败', 'error') }
  undone.value = null
}
async function togglePin(c: Conversation) {
  const next = !c.pinned
  c.pinned = next
  try { await conversationsApi.patch(c.id, { pinned: next }) }
  catch (e: any) { c.pinned = !next; toast.show(e.message ?? '操作失败', 'error') }
}
function when(s: string | null) {
  if (!s) return ''
  const d = new Date(s)
  const today = new Date().toDateString() === d.toDateString()
  return today ? d.toTimeString().slice(0, 5) : `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')}`
}
const results = ref<SearchResult[]>([])
const searching = ref(false)
const searchErr = ref('')
let searchTimer: number | undefined

watch(q, (v) => {
  window.clearTimeout(searchTimer)
  const k = v.trim()
  if (!k) { results.value = []; searchErr.value = ''; searching.value = false; return }
  searching.value = true
  searchTimer = window.setTimeout(async () => {
    try {
      const d = await searchApi.query(k)
      results.value = d.items
      searchErr.value = ''
    } catch (e: any) { searchErr.value = e.message ?? '搜索失败'; results.value = [] }
    finally { searching.value = false }
  }, 300)
})

const groups = computed(() => {
  const map = new Map<string, SearchResult[]>()
  for (const r of results.value) {
    const key = r.title ?? (r.scope === 'dm' ? '会话' : '房间')
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(r)
  }
  return [...map.entries()]
})

function segments(snippet: string, match: string): { text: string; hit: boolean }[] {
  if (!match) return [{ text: snippet, hit: false }]
  const out: { text: string; hit: boolean }[] = []
  const lower = snippet.toLowerCase()
  const m = match.toLowerCase()
  let i = 0
  for (;;) {
    const pos = lower.indexOf(m, i)
    if (pos < 0) { out.push({ text: snippet.slice(i), hit: false }); break }
    if (pos > i) out.push({ text: snippet.slice(i, pos), hit: false })
    out.push({ text: snippet.slice(pos, pos + match.length), hit: true })
    i = pos + match.length
  }
  return out.filter((x) => x.text)
}

function openResult(r: SearchResult) {
  const path = r.scope === 'dm' ? `/c/${r.conversation_id}` : `/r/${r.room_id}`
  void router.push(`${path}?msg=${r.message_id}`)
}

onMounted(load)
</script>

<template>
  <div class="app-container">
    <NavBar title="消息">
      <template #right>
        <button class="icon-btn" aria-label="好友" @click="router.push('/friends')">
          <AppIcon name="people" />
        </button>
        <button class="icon-btn" aria-label="新建会话" @click="creating = true">
          <AppIcon name="plus-chat" />
        </button>
      </template>
    </NavBar>

    <div class="search">
      <AppIcon name="search" />
      <input v-model="q" placeholder="搜索会话与消息内容" />
    </div>

    <div v-if="undone" class="undo">
      <span>已删除「{{ undone.conv.title }}」</span>
      <button @click="undo">撤销</button>
    </div>

    <div v-if="q.trim()" class="list">
      <p v-if="searching" class="hint">搜索中…</p>
      <div v-else-if="searchErr" class="err-tip">
        <AppIcon name="warning" /><span>{{ searchErr }}</span>
      </div>
      <EmptyState v-else-if="!results.length" icon="tray" title="没有匹配的消息"
                  desc="换个关键词试试，支持中文内容搜索" />
      <template v-else>
        <section v-for="[title, items] in groups" :key="title" class="sgroup">
          <p class="ghead"><AppIcon :name="items[0].scope === 'dm' ? 'chat' : 'door-in'" />{{ title }}</p>
          <article v-for="r in items" :key="r.message_id" class="srow" @click="openResult(r)">
            <p class="snip">
              <template v-for="(seg, i) in segments(r.snippet, r.match)" :key="i">
                <mark v-if="seg.hit">{{ seg.text }}</mark>
                <template v-else>{{ seg.text }}</template>
              </template>
            </p>
            <span class="stime">{{ when(r.created_at) }}</span>
          </article>
        </section>
      </template>
    </div>

    <div v-else class="list">
      <p v-if="loading" class="hint">加载中…</p>
      <EmptyState v-else-if="!filtered.length" icon="bubble"
                  :title="q ? '没有匹配的会话' : '还没有会话'"
                  :desc="q ? '换个关键词试试' : '新建一个会话，开始和 AI 聊天'">
        <button v-if="!q" class="primary sm" @click="creating = true">新建会话</button>
      </EmptyState>
      <article v-for="c in filtered" :key="c.id" class="row" :class="{ pinned: c.pinned }"
               @click="router.push(`/c/${c.id}`)">
        <i v-if="c.pinned" class="pin" />
        <Avatar icon="robot" tone="ai" />
        <div class="main">
          <div class="top"><span class="title">{{ c.title }}</span><span class="time">{{ when(c.last_message_at) }}</span></div>
          <div class="bottom">
            <span class="last">{{ c.message_count ? `${c.message_count} 条消息` : '还没有消息，点开开始聊' }}</span>
            <button class="mini" :aria-label="c.pinned ? '取消置顶' : '置顶'" @click.stop="togglePin(c)">
              <AppIcon :name="c.pinned ? 'pin-off' : 'pin'" />
            </button>
            <button class="mini danger" aria-label="删除会话" @click.stop="remove(c)">
              <AppIcon name="trash" />
            </button>
          </div>
        </div>
      </article>
    </div>

    <div class="pad-bottom" />
    <TabBar active="msgs" />

    <Drawer :open="creating" title="新建会话" desc="选择模型后即可开始，切换模型不会串上下文"
            @close="creating = false">
      <label class="fl">会话标题</label>
      <input v-model="newTitle" class="fi" placeholder="例如：产品方案讨论" />
      <label class="fl">模型</label>
      <select v-model="newModel" class="fi">
        <option v-for="m in models" :key="m.public_name" :value="m.public_name">
          {{ m.display_name }}（{{ m.public_name }}）
        </option>
      </select>
      <p v-if="!models.length" class="warn-tip">
        当前没有可用模型。请先到「我的 → 模型接口配置」添加渠道，并在模型注册表里绑定。
      </p>
      <template #footer>
        <button class="primary" :disabled="!models.length" @click="create">创建并开始</button>
      </template>
    </Drawer>
  </div>
</template>

<style scoped>
.icon-btn { background: none; border: none; color: var(--t2); cursor: pointer; padding: 6px; }
.search { position: relative; padding: 8px 12px; background: var(--surface); border-bottom: 1px solid var(--line); }
.search .app-icon { position: absolute; left: 22px; top: 50%; transform: translateY(-50%); width: 17px; height: 17px; color: var(--t4); }
.search input { width: 100%; padding: 8px 12px 8px 34px; background: var(--surface-2); border: 1px solid transparent;
  border-radius: 18px; font-size: var(--fs-md); color: var(--t1); outline: none; }
.search input:focus { border-color: var(--accent); background: var(--surface); }
.undo { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 8px 12px 0;
  padding: 8px 12px; background: var(--warn-soft); border: 1px solid var(--warn-line); border-radius: var(--r-sm);
  font-size: var(--fs-cap); color: var(--warn); }
.undo button { background: none; border: none; color: var(--warn); font-weight: 700; cursor: pointer; }
.list { flex: 1; }
.hint { padding: 24px; text-align: center; color: var(--t4); font-size: var(--fs-sm); }
.row { display: flex; gap: 10px; align-items: center; padding: 11px 12px; background: var(--surface);
  border-bottom: 1px solid var(--line); cursor: pointer; position: relative; }
.row.pinned { background: var(--surface-2); }
.pin { position: absolute; top: 0; right: 0; width: 0; height: 0; border-top: 14px solid var(--accent);
  border-left: 14px solid transparent; opacity: .85; }
.main { flex: 1; min-width: 0; }
.top { display: flex; align-items: baseline; gap: 8px; }
.title { flex: 1; min-width: 0; font-size: var(--fs-lg); font-weight: 600; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.time { font-size: 10px; color: var(--t4); flex-shrink: 0; }
.bottom { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.last { flex: 1; min-width: 0; font-size: var(--fs-sm); color: var(--t3); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.mini { background: none; border: none; color: var(--t4); cursor: pointer; padding: 2px; }
.mini .app-icon { width: 16px; height: 16px; }
.mini.danger:hover { color: var(--err); }
.fl { display: block; font-size: var(--fs-cap); font-weight: 600; color: var(--t2); margin: 10px 0 4px; }
.fi { width: 100%; padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--t1); font-size: var(--fs-md); outline: none; }
.warn-tip { margin-top: 10px; font-size: var(--fs-cap); color: var(--warn); background: var(--warn-soft);
  padding: 8px 10px; border-radius: var(--r-sm); line-height: 1.5; }
.primary { width: 100%; padding: 12px 0; border: none; border-radius: var(--r-sm); background: var(--accent);
  color: #fff; font-size: var(--fs-lg); font-weight: 600; cursor: pointer; }
.primary:disabled { opacity: .5; cursor: not-allowed; }
.primary.sm { width: auto; padding: 8px 18px; font-size: var(--fs-md); margin-top: 12px; }
.pad-bottom { height: 72px; }
.sgroup { margin-bottom: 4px; }
.ghead { display: flex; align-items: center; gap: 6px; padding: 8px 12px 4px; font-size: var(--fs-cap);
  font-weight: 700; color: var(--t3); }
.ghead .app-icon { width: 14px; height: 14px; }
.srow { display: flex; align-items: center; gap: 8px; padding: 9px 12px; background: var(--surface);
  border-bottom: 1px solid var(--line); cursor: pointer; }
.snip { flex: 1; min-width: 0; font-size: var(--fs-sm); color: var(--t2); line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.snip mark { background: var(--accent-soft); color: var(--accent); border-radius: 3px; padding: 0 1px; }
.stime { font-size: 10px; color: var(--t4); flex-shrink: 0; }
.err-tip { display: flex; align-items: center; gap: 8px; margin: 12px; padding: 10px 12px;
  background: var(--err-soft, #fdecea); border-radius: var(--r-sm); color: var(--err);
  font-size: var(--fs-sm); }
.err-tip .app-icon { width: 16px; height: 16px; flex-shrink: 0; }
</style>
